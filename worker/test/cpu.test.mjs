// Every route of the Worker, and the documents pass, within a CPU budget (ADR 0019): the free
// plan allows 10 ms of CPU a request, and a PDF render costs seconds. Node's CPU is not the
// Worker's (sqlite in-process here, D1 over the network there), so the budget is 5 ms a call:
// half the plan's limit, ten times what a D1 + JSON route costs, a hundredth of a render.
//
// Measure: one warm-up call (JIT, JWKS, module init), then ITERATIONS calls timed as one block
// with process.cpuUsage (user + system; network waits are not CPU) and the mean per call is
// compared. The mean is needed: on Windows cpuUsage ticks by 15.6 ms, so a single call reads
// 0, 16 or 31 ms whatever it cost.
//
// In production, after a deploy: Cloudflare dashboard -> Workers & Pages -> job-match ->
// Metrics -> "CPU time": P50 / P99 / P999 must stay under 10 ms, and "Errors" must show no
// 1102 (`wrangler tail` shows no CPU figure). Before ADR 0019 the first download hit 1102.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { before, beforeEach, describe, test } from "node:test";

import { resetJwksCache } from "../src/auth.js";
import worker, { runDocumentsScheduled } from "../src/index.js";
import { env, fakeAssets, fakeD1, fakeR2, identityProvider, request } from "./helpers.mjs";

const BUDGET_MS = 5; // per call, mean over ITERATIONS
const ITERATIONS = 20;
const KEY = "france_travail:CPU001";
const NOW = new Date("2026-11-04T08:10:00Z");

let idp;
let db;
let token;
let docs;

before(async () => {
  idp = await identityProvider();
});

beforeEach(async () => {
  resetJwksCache();
  idp.hosts = {};
  db = fakeD1();
  docs = fakeR2({
    "master/cv_master.json": { headline: "DevOps", experiences: [], projects: [], skills: [], skill_groups: [], education: [], certifications: [], languages: [], extras: [] },
    "master/contact.json": { first_name: "A", last_name: "B", title: "DevOps", email: "a@example.com", phone: "0", linkedin: "", github: "", location: "Lyon" },
    ["docs/" + KEY + "/v1/content.json"]: { job_key: KEY, version: 1, offer: { company: "Initech" } },
  });
  token = await idp.sign();
  const stamp = NOW.toISOString();
  db.raw.prepare("INSERT INTO applications (job_key, status, updated_at) VALUES (?, 'to_apply', ?)").run(KEY, stamp);
  db.raw.prepare("INSERT INTO documents (job_key, version, status, content_key, created_at, updated_at) VALUES (?, 1, 'ready', ?, ?, ?)")
    .run(KEY, "docs/" + KEY + "/v1/content.json", stamp, stamp);
  db.raw.prepare("INSERT INTO decisions (job_key, label, score_at_decision, created_at) VALUES (?, 'good_fit', 80, ?)").run(KEY, stamp);
});

function cpuEnv() {
  return env(db, {
    ASSETS: fakeAssets({ "/data.json": { thresholds: { strong: 80, min_score: 55 }, jobs: [{ key: KEY, title: "DevOps", company: "Initech", score: 80 }], tracked: [] } }),
    ANTHROPIC_API_KEY: "sk-ant-test-secret",
    ACCESS_SERVICE_CN: "abc.access",
    DOCS: docs,
  });
}

// The mean CPU time of one call, user + system, in milliseconds: one warm-up call not
// counted, then ITERATIONS calls timed together.
async function meanCpuMs(fn) {
  await fn();
  const before = process.cpuUsage();
  for (let i = 0; i < ITERATIONS; i++) await fn();
  const d = process.cpuUsage(before);
  return (d.user + d.system) / 1000 / ITERATIONS;
}

// Every route of index.js's header, with a body when it takes one.
const ROUTES = [
  ["GET", "/api/applications"],
  ["PUT", `/api/applications/${KEY}`, { status: "applied", applied_at: "2026-11-04" }],
  ["POST", "/api/decisions", { job_key: KEY, label: "good_fit", score_at_decision: 80 }],
  ["DELETE", "/api/decisions/1"],
  ["PUT", "/api/skill-overrides/kubernetes"],
  ["DELETE", "/api/skill-overrides/kubernetes"],
  ["GET", `/api/documents/${KEY}`],
  ["POST", `/api/documents/${KEY}/regenerate`],
  ["GET", `/api/documents/${KEY}/v1/content.json`],
  ["POST", "/api/ai/run"],
  ["POST", "/api/documents/run"],
  ["POST", "/api/documents/missing"],
  ["GET", "/api/followups/due"],
  ["PUT", "/api/inbox/x", { action: "ignore" }],
];

describe("CPU budget", () => {
  test("the header lists every route this test calls", () => {
    const header = readFileSync(new URL("../src/index.js", import.meta.url), "utf8").split("\nimport ")[0];
    const listed = [...header.matchAll(/^\/\/ +(GET|PUT|POST|DELETE) +(\/api\/[^ ]+)/gm)].map((m) => m[2]);
    for (const [, path] of ROUTES) {
      const pattern = path.replace(KEY, ":key").replace(/\/decisions\/1$/, "/decisions/:id").replace(/\/skill-overrides\/\w+$/, "/skill-overrides/:skill").replace(/\/inbox\/x$/, "/inbox/:message_id").replace(/\/v1\//, "/v<n>/");
      assert.ok(listed.includes(pattern), `${pattern} missing from the header (${listed.join(", ")})`);
    }
    assert.ok(listed.includes("/api/inbox")); // POST /api/inbox needs Haiku: covered by inbox.test.mjs
  });

  for (const [method, path, body] of ROUTES) {
    test(`${method} ${path} stays under ${BUDGET_MS} ms of CPU a call`, async () => {
      const ms = await meanCpuMs(async () => {
        const waited = [];
        const ctx = { waitUntil: (p) => waited.push(p.catch(() => {})) };
        const res = await worker.fetch(request(path, { method, token, body }), cpuEnv(), ctx);
        await Promise.all(waited); // the background passes count too
        // a repeated call may answer 404 or 409 (the decision is deleted, the row changed): never a 5xx
        assert.ok(res.status < 500, `${method} ${path} -> ${res.status}`);
      });
      assert.ok(ms < BUDGET_MS, `${method} ${path}: ${ms.toFixed(2)} ms of CPU a call`);
    });
  }

  test("the documents pass renders nothing: under budget with a ready row and a pending one", async () => {
    idp.hosts["api.anthropic.com"] = async () => new Response(JSON.stringify({ error: { message: "down" } }), { status: 503 });
    let version = 1;
    const ms = await meanCpuMs(async () => {
      // one fresh pending row a pass, so every pass takes a row and calls the (failing) API
      version += 1;
      db.raw.prepare("INSERT INTO documents (job_key, version, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)").run(KEY, version, NOW.toISOString(), NOW.toISOString());
      const r = await runDocumentsScheduled(cpuEnv(), { fetch: globalThis.fetch, now: NOW });
      assert.equal(r.outcome, "ok");
      assert.ok(!("rendered" in r.counters) && !("render_errors" in r.counters));
    });
    assert.ok(ms < BUDGET_MS, `documents pass: ${ms.toFixed(2)} ms of CPU a pass`);
  });
});
