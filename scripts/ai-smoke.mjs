#!/usr/bin/env node
// Smoke test of the AI rerank (ADR 0016) against the real providers, from a local `wrangler dev`.
//
//   node scripts/ai-smoke.mjs             3 verdicts through the Claude API (Haiku)
//   node scripts/ai-smoke.mjs --fallback  3 more through Workers AI (AI_PROVIDER forced)
//   node scripts/ai-smoke.mjs --reset     empty the AI tables of the LOCAL D1
//   node scripts/ai-smoke.mjs --limit 5   another cap than 3
//
// Before the first run (once):
//   - `.dev.vars` (gitignored) holds ANTHROPIC_API_KEY=sk-ant-...;
//   - `npx wrangler@4 d1 migrations apply job-match --local`;
//   - `job-match dashboard --out site` with config/profile.yaml present, so that site/ carries
//     data.json and ai-profile.json (the Worker reads them from the local disk).
//
// Why local and not `--remote`: in `wrangler dev`, Workers AI always runs remotely (real
// neurons), static assets are always served from the local disk, and D1 stays local unless the
// config says `remote: true`, which this repo forbids (never the production D1 in dev). So the
// calls are real, and the rows land in the local D1 (.wrangler/state), read back here.
//
// Output: counters and HTTP codes only. The Worker's own log line (`ai rerank ...`) is the same.
// Never the key, never a prompt, never an answer.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
};
const PORT = Number(option("--port", "8787"));
const LIMIT = Number(option("--limit", "3"));
const CRON = "30 7 * * *";
const npx = process.platform === "win32" ? "npx.cmd" : "npx";
const WRANGLER = [npx, "--yes", "wrangler@4"];

function d1(sql) {
  const r = spawnSync(WRANGLER[0], [...WRANGLER.slice(1), "d1", "execute", "job-match", "--local", "--json", "--command", sql], {
    encoding: "utf8", shell: process.platform === "win32",
  });
  if (r.status !== 0) {
    console.error("d1 execute failed (status " + r.status + ")");
    process.exit(1);
  }
  const text = r.stdout.slice(r.stdout.indexOf("["));
  return JSON.parse(text)[0].results;
}

if (flag("--reset")) {
  for (const t of ["ai_verdicts", "ai_usage", "disagreements", "ai_runs"]) d1("DELETE FROM " + t);
  console.log("local D1: AI tables emptied");
  process.exit(0);
}

for (const f of ["site/data.json", "site/ai-profile.json", ".dev.vars"]) {
  if (!existsSync(f)) {
    console.error("missing " + f + " (see the header of this script)");
    process.exit(1);
  }
}

const before = Object.fromEntries(d1("SELECT provider, COUNT(*) AS n FROM ai_verdicts GROUP BY provider").map((r) => [r.provider, r.n]));

const devArgs = [...WRANGLER.slice(1), "dev", "--test-scheduled", "--port", String(PORT), "--var", "AI_DAILY_LIMIT:" + LIMIT];
if (flag("--fallback")) devArgs.push("--var", "AI_PROVIDER:workers_ai");
const dev = spawn(WRANGLER[0], devArgs, { stdio: ["ignore", "pipe", "pipe"], shell: process.platform === "win32" });

let ready = false;
const onLine = (chunk) => {
  for (const line of String(chunk).split(/\r?\n/)) {
    if (!line) continue;
    if (/ai rerank/.test(line)) console.log("worker: " + line.trim());
    if (/Ready on|http:\/\/(127\.0\.0\.1|localhost):\d+/.test(line)) ready = true;
  }
};
dev.stdout.on("data", onLine);
dev.stderr.on("data", onLine);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function trigger() {
  for (const path of ["/__scheduled", "/cdn-cgi/local/scheduled"]) {
    const url = "http://127.0.0.1:" + PORT + path + "?cron=" + encodeURIComponent(CRON);
    try {
      const res = await fetch(url);
      if (res.status === 200) return path;
    } catch {
      /* not up yet */
    }
  }
  return null;
}

function stop() {
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(dev.pid), "/T", "/F"], { stdio: "ignore" });
  else dev.kill("SIGTERM");
}

(async () => {
  for (let i = 0; i < 60 && !ready; i++) await sleep(1000);
  if (!ready) {
    console.error("wrangler dev did not come up in 60 s");
    stop();
    process.exit(1);
  }
  await sleep(1500);
  const route = await trigger();
  if (!route) {
    console.error("the scheduled route answered neither /__scheduled nor /cdn-cgi/local/scheduled");
    stop();
    process.exit(1);
  }
  console.log("scheduled handler triggered through " + route + " (limit " + LIMIT + (flag("--fallback") ? ", provider forced to workers_ai" : "") + ")");
  // The handler runs in waitUntil: give the calls time to finish (a few seconds each).
  await sleep(LIMIT * 8000 + 5000);
  stop();
  await sleep(1000);

  const after = Object.fromEntries(d1("SELECT provider, COUNT(*) AS n FROM ai_verdicts GROUP BY provider").map((r) => [r.provider, r.n]));
  const delta = {};
  for (const p of new Set([...Object.keys(before), ...Object.keys(after)])) delta[p] = (after[p] || 0) - (before[p] || 0);
  console.log("new verdicts by provider: " + JSON.stringify(delta));
  const usage = d1("SELECT day, provider, calls, tokens_in, tokens_out FROM ai_usage ORDER BY day DESC, provider LIMIT 4");
  console.log("ai_usage: " + JSON.stringify(usage));
  const run = d1("SELECT started_at, outcome, http_status, provider, counters FROM ai_runs ORDER BY id DESC LIMIT 1")[0];
  console.log("last ai_runs row: " + JSON.stringify(run || null));
  const stopped = run && run.outcome !== "ok";
  const expected = Object.values(delta).reduce((a, b) => a + b, 0) === LIMIT;
  console.log(stopped ? "FAIL: the run did not end ok" : expected ? "OK: " + LIMIT + " new verdicts" : "WARN: " + Object.values(delta).reduce((a, b) => a + b, 0) + " new verdicts (cache or cap?)");
  process.exit(stopped ? 1 : 0);
})();
