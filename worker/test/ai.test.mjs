import assert from "node:assert/strict";
import { before, beforeEach, describe, test } from "node:test";

import {
  ANTHROPIC_MODEL,
  ANTHROPIC_URL,
  buildSystem,
  buildSystemText,
  buildUser,
  DAILY_LIMIT,
  disagreement,
  listRuns,
  listVerdicts,
  PROMPT_VERSION,
  runRerank,
  selectCandidates,
  validateVerdict,
  VERDICT_SCHEMA,
  WORKERS_AI_MODEL,
} from "../src/ai.js";
import { resetJwksCache } from "../src/auth.js";
import worker, { runScheduled } from "../src/index.js";
import { env, fakeAssets, fakeD1, identityProvider, request } from "./helpers.mjs";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const PROFILE = {
  preferred: [{ name: "kubernetes", band: "fort" }, { name: "terraform", band: "moyen" }],
  negative: [{ name: "php" }],
  experience_years: 2,
  contract_types: ["CDI"],
  mobility: "france",
};
const NOW = new Date("2026-10-25T07:30:00Z");

function job(key, score, extra = {}) {
  return {
    key,
    ai_hash: HASH_A,
    score,
    section: score >= 80 ? "strong" : "eligible",
    title: "Ingénieur DevOps",
    company: "Acme",
    contract: "CDI",
    required_years: 2,
    description_excerpt: "Kubernetes, Terraform, GitLab CI. Astreinte une semaine sur quatre.",
    ...extra,
  };
}

function data(jobs, minScore = 55) {
  return { thresholds: { strong: 80, min_score: minScore }, jobs };
}

function verdict(relevance, level = "fort", reasons = ["Stack Kubernetes et Terraform citée."], red_flags = []) {
  return { relevance, level, reasons, red_flags };
}

// A Claude API double: `answers` is a queue of {status, body} or of verdict objects.
function anthropic(answers) {
  const calls = [];
  const handler = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    const next = answers.length ? answers.shift() : verdict(80);
    if (next && typeof next.status === "number") {
      return new Response(JSON.stringify(next.body || {}), { status: next.status });
    }
    const text = typeof next === "string" ? next : JSON.stringify(next);
    return new Response(
      JSON.stringify({
        content: [{ type: "text", text }],
        stop_reason: "end_turn",
        usage: { input_tokens: 1200, cache_read_input_tokens: 900, output_tokens: 80 },
      }),
      { status: 200 },
    );
  };
  return { calls, handler };
}

function workersAI(answers) {
  const calls = [];
  return {
    calls,
    run: async (model, input) => {
      calls.push({ model, input });
      const next = answers.length ? answers.shift() : verdict(70, "tenter");
      if (next instanceof Error) throw next;
      return { response: next, usage: { prompt_tokens: 1500, completion_tokens: 90 } };
    },
  };
}

let idp;
let db;
let logged;
const realLog = console.log;

before(async () => {
  idp = await identityProvider();
});

beforeEach(() => {
  resetJwksCache();
  idp.hosts = {};
  db = fakeD1();
  logged = [];
  console.log = (...args) => logged.push(args.map(String).join(" "));
});

function aiEnv(files, overrides = {}) {
  return env(db, {
    ASSETS: fakeAssets({ "/ai-profile.json": PROFILE, "/data.json": data([job("ft:1", 85)]), ...files }),
    ANTHROPIC_API_KEY: "sk-ant-test-secret",
    ...overrides,
  });
}

function runFull(e, opts = {}) {
  return runRerank(e, { fetch: globalThis.fetch, now: NOW, ...opts });
}
async function run(e, opts = {}) {
  return (await runFull(e, opts)).counters;
}

function count(table) {
  return db.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;
}

describe("prompt and schema", () => {
  test("the schema is strict and asks for the four fields", () => {
    assert.equal(VERDICT_SCHEMA.additionalProperties, false);
    assert.deepEqual(VERDICT_SCHEMA.required, ["relevance", "level", "reasons", "red_flags"]);
    assert.ok(!JSON.stringify(VERDICT_SCHEMA).includes('"minimum"'), "ranges are checked in code");
  });

  test("the system block is cached, stable and long enough to cache", () => {
    const a = buildSystem(PROFILE);
    const b = buildSystem({ mobility: "france", contract_types: ["CDI"], experience_years: 2, negative: [{ name: "php" }], preferred: PROFILE.preferred });
    assert.deepEqual(a[0].cache_control, { type: "ephemeral" });
    assert.equal(a[0].text, b[0].text, "key order does not change the bytes");
    // 512 tokens at the least; French runs about 3 characters per token.
    assert.ok(buildSystemText(PROFILE).length > 512 * 3, `only ${buildSystemText(PROFILE).length} characters`);
    assert.ok(a[0].text.includes("<offre>"), "the delimiters are announced");
  });

  test("the user turn carries only the offer, between delimiters", () => {
    const u = buildUser(job("ft:1", 85, { description_excerpt: "x".repeat(6000) }));
    assert.ok(u.includes("<offre>\nTitre : Ingénieur DevOps"));
    assert.ok(u.endsWith("</offre>"));
    assert.ok(u.length < 5400, "the description is capped");
    assert.ok(!u.includes("kubernetes"), "nothing from the profile");
  });
});

describe("validateVerdict", () => {
  test("accepts a verdict in range", () => {
    assert.deepEqual(validateVerdict(verdict(84, "fort", [" a "], ["b"])), {
      score: 84, level: "fort", reasons: ["a"], red_flags: ["b"],
    });
  });

  const bad = {
    "score above 100": verdict(101),
    "negative score": verdict(-1),
    "fractional score": verdict(50.5),
    "score as a string": verdict("80"),
    "unknown level": verdict(80, "maybe"),
    "four reasons": verdict(80, "fort", ["a", "b", "c", "d"]),
    "a reason too long": verdict(80, "fort", ["x".repeat(161)]),
    "an empty reason": verdict(80, "fort", [""]),
    "a non-string flag": verdict(80, "fort", ["a"], [1]),
    "an extra key": { ...verdict(80), note: "x" },
    "a missing key": { relevance: 80, level: "fort", reasons: [] },
    "an array": [verdict(80)],
    "null": null,
  };
  for (const [name, value] of Object.entries(bad)) {
    test(`rejects ${name}`, () => assert.equal(validateVerdict(value), null));
  }
});

describe("selectCandidates", () => {
  test("keeps offers at or above the threshold, best first, without the cached ones", () => {
    const d = data([job("ft:1", 60), job("ft:2", 90), job("ft:3", 54), job("ft:4", 70, { ai_hash: HASH_B }), { key: "ft:5", score: 99 }]);
    const r = selectCandidates(d, new Set(["ft:4|" + HASH_B]), 10);
    assert.equal(r.eligible, 3);
    assert.equal(r.cached, 1);
    assert.deepEqual(r.candidates.map((j) => j.key), ["ft:2", "ft:1"]);
    assert.equal(r.skipped_cap, 0);
  });

  test("the limit cuts the tail and counts it", () => {
    const d = data([job("ft:1", 60), job("ft:2", 90), job("ft:3", 70)]);
    const r = selectCandidates(d, new Set(), 2);
    assert.deepEqual(r.candidates.map((j) => j.key), ["ft:2", "ft:3"]);
    assert.equal(r.skipped_cap, 1);
  });
});

describe("disagreement", () => {
  test("a gap over 25 points", () => assert.equal(disagreement(60, "eligible", { score: 90, level: "fort" }), "gap"));
  test("exactly 25 is not a gap", () => assert.equal(disagreement(60, "eligible", { score: 85, level: "fort" }), null));
  test("off-topic on a strong offer wins over the gap", () =>
    assert.equal(disagreement(85, "strong", { score: 20, level: "hors_sujet" }), "off_topic_strong"));
  test("off-topic on an eligible offer is a gap at most", () =>
    assert.equal(disagreement(56, "eligible", { score: 35, level: "hors_sujet" }), null));
});

describe("runRerank", () => {
  test("one verdict per offer through the Claude API, with the documented request shape", async () => {
    const api = anthropic([verdict(84, "fort", ["Kubernetes cité."], ["Astreinte non annoncée dans le titre."])]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const c = await run(aiEnv());
    assert.equal(c.scored, 1);
    assert.equal(api.calls.length, 1);
    const { url, init, body } = api.calls[0];
    assert.equal(url, ANTHROPIC_URL);
    assert.equal(init.headers["x-api-key"], "sk-ant-test-secret");
    assert.equal(init.headers["anthropic-version"], "2026-10-21");
    assert.equal(body.model, ANTHROPIC_MODEL);
    assert.equal(body.output_config.format.type, "json_schema");
    assert.equal(body.output_config.effort, "low");
    assert.equal(body.system[0].cache_control.type, "ephemeral");
    assert.equal(body.messages.length, 1);
    assert.ok(!("temperature" in body) && !("thinking" in body));
    const row = db.raw.prepare("SELECT * FROM ai_verdicts").get();
    assert.equal(row.job_key, "ft:1");
    assert.equal(row.hash, HASH_A);
    assert.equal(row.provider, "anthropic");
    assert.equal(row.prompt_version, PROMPT_VERSION);
    assert.equal(row.score, 84);
    assert.deepEqual(JSON.parse(row.red_flags), ["Astreinte non annoncée dans le titre."]);
    const usage = { ...db.raw.prepare("SELECT * FROM ai_usage").get() };
    assert.deepEqual(usage, { day: "2026-10-25", provider: "anthropic", calls: 1, tokens_in: 2100, tokens_out: 80 });
  });

  test("cache by hash: a second run sends nothing, a changed hash or prompt version sends again", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let c = await run(aiEnv());
    assert.equal(c.scored, 1);
    c = await run(aiEnv());
    assert.deepEqual([c.scored, c.cached, c.candidates], [0, 1, 0]);
    assert.equal(api.calls.length, 1);
    c = await run(aiEnv({ "/data.json": data([job("ft:1", 85, { ai_hash: HASH_B })]) }));
    assert.equal(c.scored, 1);
    assert.equal(api.calls.length, 2);
    db.raw.prepare("UPDATE ai_verdicts SET prompt_version = '0'").run();
    c = await run(aiEnv({ "/data.json": data([job("ft:1", 85, { ai_hash: HASH_B })]) }));
    assert.equal(c.scored, 1);
    assert.equal(api.calls.length, 3);
    assert.equal(count("ai_verdicts"), 3);
  });

  test("the daily cap counts calls already made today, retries included", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-10-25', 'anthropic', 2, 0, 0)").run();
    const jobs = [job("ft:1", 90), job("ft:2", 80), job("ft:3", 70), job("ft:4", 60)];
    const c = await run(aiEnv({ "/data.json": data(jobs) }), { limit: 4 });
    assert.deepEqual([c.candidates, c.scored, c.skipped_cap], [2, 2, 2]);
    assert.deepEqual(api.calls.map((x) => x.body.messages[0].content.includes("Titre")), [true, true]);
    assert.equal(db.raw.prepare("SELECT calls FROM ai_usage").get().calls, 4);
  });

  test("the default cap is DAILY_LIMIT, AI_DAILY_LIMIT overrides it", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const jobs = Array.from({ length: 3 }, (_, i) => job("ft:" + i, 90));
    const c = await run(aiEnv({ "/data.json": data(jobs) }, { AI_DAILY_LIMIT: "2" }));
    assert.deepEqual([c.scored, c.skipped_cap], [2, 1]);
    assert.equal(DAILY_LIMIT, 100);
  });

  test("invalid JSON: one retry, then the offer is skipped and the next one goes on", async () => {
    const api = anthropic(["not json", verdict(300), verdict(77, "tenter")]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }));
    assert.deepEqual([c.scored, c.invalid], [1, 2]);
    assert.equal(api.calls.length, 3);
    assert.equal(db.raw.prepare("SELECT job_key FROM ai_verdicts").get().job_key, "ft:2");
  });

  test("credit spent (402) switches to Workers AI for the rest of the run", async () => {
    const api = anthropic([{ status: 402, body: { error: { type: "billing_error", message: "credit" } } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const ai = workersAI([verdict(66, "tenter"), JSON.stringify(verdict(40, "tenter"))]);
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }, { AI: ai }));
    assert.deepEqual([c.scored, c.fallback, c.errors], [2, 1, 0]);
    assert.equal(api.calls.length, 1);
    assert.equal(ai.calls.length, 2);
    assert.equal(ai.calls[0].model, WORKERS_AI_MODEL);
    assert.equal(ai.calls[0].input.response_format.type, "json_schema");
    const providers = db.raw.prepare("SELECT provider FROM ai_verdicts ORDER BY id").all().map((r) => r.provider);
    assert.deepEqual(providers, ["workers_ai", "workers_ai"]);
    const usage = db.raw.prepare("SELECT provider, calls FROM ai_usage ORDER BY provider").all().map((r) => ({ ...r }));
    assert.deepEqual(usage, [{ provider: "anthropic", calls: 1 }, { provider: "workers_ai", calls: 2 }]);
  });

  test("a 400 that names the credit balance and a 429 fall back the same way", async () => {
    for (const first of [
      { status: 400, body: { error: { type: "invalid_request_error", message: "Your credit balance is too low" } } },
      { status: 429, body: { error: { type: "rate_limit_error", message: "slow down" } } },
    ]) {
      db = fakeD1();
      const api = anthropic([first]);
      idp.hosts["api.anthropic.com"] = api.handler;
      const ai = workersAI([]);
      const c = await run(aiEnv({}, { AI: ai }));
      assert.deepEqual([c.scored, c.fallback], [1, 1]);
    }
  });

  test("without a Workers AI binding, a spent credit ends the run with an error count", async () => {
    const api = anthropic([{ status: 402, body: {} }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }));
    assert.deepEqual([c.scored, c.errors, c.fallback], [0, 1, 0]);
    assert.equal(api.calls.length, 1);
  });

  test("Workers AI failing too leaves the offer to the Python score", async () => {
    const api = anthropic([{ status: 402, body: {} }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const ai = workersAI([new Error("neurons exhausted"), new Error("neurons exhausted"), verdict(50, "tenter")]);
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }, { AI: ai }));
    assert.deepEqual([c.scored, c.errors], [1, 2]);
    assert.equal(db.raw.prepare("SELECT job_key FROM ai_verdicts").get().job_key, "ft:2");
  });

  test("a 5xx is retried once, then skipped; a refusal is not retried", async () => {
    const api = anthropic([{ status: 529, body: {} }, verdict(80), { status: 200, body: { stop_reason: "refusal", content: [] } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }));
    assert.deepEqual([c.scored, c.errors, c.refused], [1, 1, 1]);
    assert.equal(api.calls.length, 3);
  });

  test("disagreements are stored with both scores", async () => {
    const api = anthropic([verdict(30, "hors_sujet"), verdict(95, "fort"), verdict(70, "tenter")]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const c = await run(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 60), job("ft:3", 58)]) }));
    assert.equal(c.disagreements, 2);
    const rows = db.raw.prepare("SELECT job_key, kind, python_score, ai_score FROM disagreements ORDER BY id").all().map((r) => ({ ...r }));
    assert.deepEqual(rows, [
      { job_key: "ft:1", kind: "off_topic_strong", python_score: 90, ai_score: 30 },
      { job_key: "ft:2", kind: "gap", python_score: 60, ai_score: 95 },
    ]);
  });

  test("no profile summary: nothing is sent", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await runFull(env(db, { ASSETS: fakeAssets({ "/data.json": data([job("ft:1", 90)]) }), ANTHROPIC_API_KEY: "k" }));
    assert.equal(r.outcome, "no_profile");
    assert.equal(api.calls.length, 0);
  });

  test("no key and no binding: a failed run with an error count, nothing else", async () => {
    const r = await runFull(aiEnv({}, { ANTHROPIC_API_KEY: undefined }));
    assert.equal(r.outcome, "failed");
    assert.deepEqual([r.counters.errors, r.counters.scored], [1, 0]);
  });

  test("a 4xx that is not a quota (unknown model, bad key, refused schema) stops the run with its status", async () => {
    for (const [status, body] of [
      [404, { error: { type: "not_found_error", message: "model: claude-haiku-9" } }],
      [401, { error: { type: "authentication_error", message: "invalid x-api-key" } }],
      [400, { error: { type: "invalid_request_error", message: "output_config.format.schema: unsupported keyword" } }],
    ]) {
      db = fakeD1();
      const api = anthropic([{ status, body }, verdict(80)]);
      idp.hosts["api.anthropic.com"] = api.handler;
      const ai = workersAI([]);
      const r = await runFull(aiEnv({ "/data.json": data([job("ft:1", 90), job("ft:2", 80)]) }, { AI: ai }));
      assert.equal(r.outcome, "stopped", String(status));
      assert.equal(r.http_status, status);
      assert.equal(r.provider, "anthropic");
      assert.equal(api.calls.length, 1, "no retry");
      assert.equal(ai.calls.length, 0, "no fallback");
      assert.equal(r.counters.scored, 0);
      assert.equal(count("ai_verdicts"), 0);
      assert.equal(db.raw.prepare("SELECT calls FROM ai_usage").get().calls, 1);
    }
  });

  test("AI_PROVIDER=workers_ai forces the fallback (the dev smoke test)", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const ai = workersAI([]);
    const r = await runFull(aiEnv({}, { AI: ai, AI_PROVIDER: "workers_ai" }));
    assert.equal(r.outcome, "ok");
    assert.equal(r.provider, "workers_ai");
    assert.equal(api.calls.length, 0);
    assert.equal(ai.calls.length, 1);
    assert.equal(r.counters.fallback, 0);
  });

  test("the cron logs counters only, and writes one ai_runs row", async () => {
    const api = anthropic([verdict(84, "fort", ["Une raison très reconnaissable."])]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let done;
    const ctx = { waitUntil: (p) => { done = p; } };
    await worker.scheduled({ cron: "30 7 * * *" }, aiEnv(), ctx);
    await done;
    assert.equal(logged.length, 1);
    assert.match(logged[0], /^ai rerank ok \{/);
    for (const secret of ["sk-ant", "reconnaissable", "Ingénieur DevOps", "Kubernetes", "recruteur"]) {
      assert.ok(!logged[0].includes(secret), `logged ${secret}`);
    }
    const runs = await listRuns(db);
    assert.equal(runs.length, 1);
    assert.equal(runs[0].outcome, "ok");
    assert.equal(runs[0].http_status, null);
    assert.equal(runs[0].provider, "anthropic");
    assert.equal(runs[0].counters.scored, 1);
    assert.ok(runs[0].started_at <= runs[0].finished_at);
  });

  test("a stopped run logs the HTTP status alone and keeps it in ai_runs", async () => {
    const api = anthropic([{ status: 404, body: { error: { type: "not_found_error", message: "model: secret-model-name" } } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await runScheduled(aiEnv());
    assert.equal(r.outcome, "stopped");
    assert.equal(logged.length, 1);
    assert.match(logged[0], /^ai rerank stopped http=404 \{/);
    assert.ok(!logged[0].includes("secret-model-name"));
    const runs = await listRuns(db);
    assert.deepEqual([runs[0].outcome, runs[0].http_status], ["stopped", 404]);
  });

  test("an exception inside the run is a failed row, without a message", async () => {
    const e = aiEnv();
    e.DB = { prepare: () => { throw new Error("boom with a secret"); } };
    const r = await runScheduled(e);
    assert.equal(r.outcome, "failed");
    assert.equal(logged.length, 2); // the counters line, then "run row not written"
    assert.ok(!logged.join(" ").includes("boom"));
  });
});

describe("GET /api/applications", () => {
  test("returns the latest verdict per offer with parsed reasons", async () => {
    const insert = db.raw.prepare(
      "INSERT INTO ai_verdicts (job_key, hash, provider, model, prompt_version, score, level, reasons, red_flags, created_at)" +
        " VALUES (?, ?, 'anthropic', 'm', '1', ?, ?, ?, '[]', '2026-10-25T07:30:00Z')",
    );
    insert.run("ft:1", HASH_A, 40, "tenter", '["ancienne"]');
    insert.run("ft:1", HASH_B, 84, "fort", '["récente"]');
    insert.run("ft:2", HASH_A, 10, "hors_sujet", "not json");
    const list = await listVerdicts(db);
    assert.deepEqual(list, [
      { job_key: "ft:1", hash: HASH_B, provider: "anthropic", score: 84, level: "fort", reasons: ["récente"], red_flags: [] },
      { job_key: "ft:2", hash: HASH_A, provider: "anthropic", score: 10, level: "hors_sujet", reasons: [], red_flags: [] },
    ]);
    const token = await idp.sign();
    const res = await worker.fetch(request("/api/applications", { token }), env(db));
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.ai_verdicts.length, 2);
    assert.deepEqual(Object.keys(body).sort(), ["ai_runs", "ai_verdicts", "applications", "decisions", "skill_overrides"]);
    assert.deepEqual(body.ai_runs, []);
  });
});

test("console.log is restored", () => {
  console.log = realLog;
});
