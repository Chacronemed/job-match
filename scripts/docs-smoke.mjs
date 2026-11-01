#!/usr/bin/env node
// Smoke test of the application documents (ADR 0017) against the real Claude API, from a local
// `wrangler dev`: the master CV goes to the LOCAL R2, two kept offers get a pending row in the
// LOCAL D1, the documents cron runs once, and the generated content.json files land in
// private/out/ for review, with the real cost per document.
//
//   node scripts/docs-smoke.mjs                      the two best-scored offers of site/data.json
//   node scripts/docs-smoke.mjs --keys k1,k2         chosen offers (job keys from data.json)
//   node scripts/docs-smoke.mjs --reset              empty documents, document_runs of the LOCAL D1
//   node scripts/docs-smoke.mjs --render-only        no generation: render the latest ready version of
//                                                    each offer here (render.js, the Inter font) when its
//                                                    files are missing, store them in the LOCAL R2, and
//                                                    copy PDF + DOCX (CV and letter) to private/out/;
//                                                    --force re-renders even when the files exist
//
// Before the first run (once): `.dev.vars` holds ANTHROPIC_API_KEY, `job-match dashboard --out site`
// wrote site/data.json, private/cv_master.yaml and contact.yaml validate. Migrations are applied
// here. Like ai-smoke.mjs, the AI binding makes `wrangler dev` open a remote proxy session: the
// Access service token (CLOUDFLARE_ACCESS_CLIENT_ID / _SECRET) must be in the shell env.
//
// Output: keys, statuses, tokens and dollars. Never the key, never a prompt, never a text:
// the texts are only written to private/out/ (gitignored).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
};
const PORT = Number(option("--port", "8787"));
const CRON = "*/10 * * * *";
const WIN = process.platform === "win32";
const npx = WIN ? "npx.cmd" : "npx";
const WRANGLER = [npx, "--yes", "wrangler@4"];
const JOB_MATCH = WIN ? ".venv\\Scripts\\job-match.exe" : ".venv/bin/job-match";
const PRICE_IN = 2; // USD per million tokens, claude-sonnet-5-5 (documents.js keeps the same)
const PRICE_OUT = 10;

const TMP = mkdtempSync(join(tmpdir(), "docs-smoke-"));
process.on("exit", () => rmSync(TMP, { recursive: true, force: true }));

function fail(msg, r) {
  console.error(msg);
  const err = (r.stderr || "").trim();
  const out = (r.stdout || "").trim();
  if (err) console.error(err);
  else if (out) console.error(out.slice(-1500));
  if (r.error) console.error(String(r.error));
  process.exit(1);
}

function wrangler(argv, label) {
  const r = spawnSync(WRANGLER[0], [...WRANGLER.slice(1), ...argv], { encoding: "utf8", shell: WIN });
  if (r.status !== 0) fail(label + " failed (status " + r.status + ")", r);
  return r.stdout;
}

// SQL through a temp file: with `shell: true` Node does not quote arguments on Windows.
function d1(sql) {
  const file = join(TMP, "query.sql");
  writeFileSync(file, sql + "\n");
  const out = wrangler(["d1", "execute", "job-match", "--local", "--json", "--file", file], "d1 execute");
  const start = out.indexOf("[");
  if (start < 0) fail("d1 execute returned no JSON", { stdout: out });
  return JSON.parse(out.slice(start))[0].results;
}

if (flag("--reset")) {
  d1("DELETE FROM documents; DELETE FROM document_runs;");
  console.log("local D1: documents and document_runs emptied");
  process.exit(0);
}

const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";
const FILES = { "cv.pdf": "cv_pdf_key", "cv.docx": "cv_docx_key", "letter.pdf": "letter_pdf_key", "letter.docx": "letter_docx_key" };
const ROW_COLUMNS = "job_key, version, status, error_code, first_errors, attempts, tokens_in, tokens_out, cost_micro_usd, content_key, cv_pdf_key, cv_docx_key, letter_pdf_key, letter_docx_key";
const safeKey = (k) => k.replace(/[^A-Za-z0-9._-]/g, "_");

function r2get(key, file) {
  wrangler(["r2", "object", "get", "job-match-docs/" + key, "--local", "--file", file], "r2 object get");
  return file;
}

// The four files of a version rendered here, as the Worker does it, when the row has none:
// render.js is pure, the font comes from worker/fonts/, the inputs from the local R2.
async function renderLocally(r) {
  const { renderAll, renderCvPdfInfo, cvModel } = await import("../worker/src/render.js");
  const readJson = (key, name) => JSON.parse(readFileSync(r2get(key, join(TMP, name)), "utf8"));
  const master = readJson("master/cv_master.json", "master.json");
  const contact = readJson("master/contact.json", "contact.json");
  const content = readJson(r.content_key, "content.json");
  const fonts = { regular: readFileSync("worker/fonts/Inter-Regular.ttf"), bold: readFileSync("worker/fonts/Inter-Bold.ttf") };
  const files = await renderAll(content, master, contact, fonts, new Date());
  const info = await renderCvPdfInfo(cvModel(content, master, contact), fonts);
  console.log("  CV: " + info.pages + " page" + (info.pages > 1 ? "s" : "") + ", fill " + Math.round(info.fill * 100) + " %, " + info.size + " pt, " + info.projects + " project(s)" + (info.extras ? ", engagement" : "") + (info.compact ? ", compact lines" : "") + (info.cut ? ", CUT at the bottom: too much content" : ""));
  const keys = {};
  for (const f of files) {
    const tmp = join(TMP, f.name);
    writeFileSync(tmp, f.bytes);
    const key = "docs/" + r.job_key + "/v" + r.version + "/" + f.name;
    wrangler(["r2", "object", "put", "job-match-docs/" + key, "--local", "--file", tmp, "--content-type", f.contentType], "r2 object put");
    keys[FILES[f.name]] = key;
  }
  d1(
    "UPDATE documents SET cv_pdf_key = " + q(keys.cv_pdf_key) + ", cv_docx_key = " + q(keys.cv_docx_key) +
      ", letter_pdf_key = " + q(keys.letter_pdf_key) + ", letter_docx_key = " + q(keys.letter_docx_key) +
      ", error_code = NULL, updated_at = " + q(new Date().toISOString()) +
      " WHERE job_key = " + q(r.job_key) + " AND version = " + Number(r.version) + ";",
  );
  return { ...r, ...keys };
}

// content.json, then the PDF and DOCX of the CV and the letter, into private/out/.
async function copyOut(r) {
  const base = join("private", "out", safeKey(r.job_key) + "_v" + r.version);
  r2get(r.content_key, base + ".json");
  console.log("  -> " + base + ".json");
  if (!r.cv_pdf_key || flag("--force")) r = await renderLocally(r);
  for (const [name, column] of Object.entries(FILES)) {
    if (!r[column]) continue;
    const out = base + "_" + name;
    r2get(r[column], out);
    console.log("  -> " + out);
  }
}

if (flag("--render-only")) {
  (async () => {
    mkdirSync("private/out", { recursive: true });
    const only = option("--keys", "").split(",").map((k) => k.trim()).filter(Boolean);
    const where = only.length ? " AND job_key IN (" + only.map(q).join(",") + ")" : "";
    const rows = d1("SELECT " + ROW_COLUMNS + " FROM documents WHERE status = 'ready'" + where + " AND id IN (SELECT MAX(id) FROM documents WHERE status = 'ready' GROUP BY job_key) ORDER BY job_key");
    if (!rows.length) {
      console.log("no ready document in the local D1");
      process.exit(1);
    }
    for (const r of rows) {
      console.log(r.job_key + " v" + r.version + (r.cv_pdf_key && !flag("--force") ? " (files already in R2)" : " (rendering here)"));
      await copyOut(r);
    }
    console.log("OK: " + rows.length + " versions copied to private/out/");
    process.exit(0);
  })().catch((e) => {
    console.error("render-only failed: " + (e && e.message ? e.message : e));
    process.exit(1);
  });
}

if (flag("--render-only")) await new Promise(() => {}); // the branch above exits the process

for (const f of ["site/data.json", ".dev.vars", "private/cv_master.yaml", "private/contact.yaml"]) {
  if (!existsSync(f)) {
    console.error("missing " + f + " (see the header of this script)");
    process.exit(1);
  }
}

wrangler(["d1", "migrations", "apply", "job-match", "--local"], "d1 migrations apply");
const push = spawnSync(JOB_MATCH, ["cv", "push", "--local"], { encoding: "utf8", shell: WIN });
if (push.status !== 0) fail("job-match cv push --local failed (status " + push.status + ")", push);
console.log(push.stdout.trim());

const data = JSON.parse(readFileSync("site/data.json", "utf8"));
const offers = [...(data.jobs || []), ...(data.tracked || [])];
let keys = option("--keys", "").split(",").map((k) => k.trim()).filter(Boolean);
if (!keys.length) {
  keys = [...offers].filter((j) => typeof j.score === "number").sort((a, b) => b.score - a.score).slice(0, 2).map((j) => j.key);
}
for (const k of keys) {
  if (!offers.some((j) => j.key === k)) {
    console.error("offer not in site/data.json: " + k);
    process.exit(1);
  }
}
const stamp = new Date().toISOString();
for (const k of keys) {
  d1(
    "INSERT INTO applications (job_key, status, updated_at) VALUES (" + q(k) + ", 'to_apply', " + q(stamp) + ")" +
      " ON CONFLICT(job_key) DO UPDATE SET status = 'to_apply', updated_at = excluded.updated_at;",
  );
  const open = d1("SELECT 1 AS x FROM documents WHERE job_key = " + q(k) + " AND status IN ('pending', 'running') LIMIT 1");
  if (!open.length) {
    d1(
      "INSERT INTO documents (job_key, version, status, created_at, updated_at) VALUES (" + q(k) + "," +
        " (SELECT COALESCE(MAX(version), 0) + 1 FROM documents WHERE job_key = " + q(k) + "), 'pending', " + q(stamp) + ", " + q(stamp) + ");",
    );
  }
}
console.log("pending documents for " + keys.length + " offers: " + keys.join(", "));
const before = d1("SELECT COALESCE(SUM(tokens_in), 0) AS tin, COALESCE(SUM(tokens_out), 0) AS tout FROM ai_usage WHERE model = 'claude-sonnet-5-5'")[0];

const devArgs = [...WRANGLER.slice(1), "dev", "--test-scheduled", "--port", String(PORT)];
const dev = spawn(WRANGLER[0], devArgs, { stdio: ["ignore", "pipe", "pipe"], shell: WIN });

let ready = false;
const tail = [];
const onLine = (chunk) => {
  for (const line of String(chunk).split(/\r?\n/)) {
    if (!line) continue;
    tail.push(line.trim());
    if (tail.length > 40) tail.shift();
    if (/^documents /.test(line.trim()) || /documents (ok|stopped|budget|credit|no_master|failed)/.test(line)) console.log("worker: " + line.trim());
    if (/Ready on|http:\/\/(127\.0\.0\.1|localhost):\d+/.test(line)) ready = true;
  }
};
dev.stdout.on("data", onLine);
dev.stderr.on("data", onLine);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const statuses = [];
async function trigger() {
  for (const path of ["/__scheduled", "/cdn-cgi/local/scheduled"]) {
    const url = "http://127.0.0.1:" + PORT + path + "?cron=" + encodeURIComponent(CRON);
    try {
      const res = await fetch(url);
      if (res.status === 200) return path;
      statuses.push(path + " -> " + res.status);
    } catch (e) {
      statuses.push(path + " -> " + (e.cause && e.cause.code ? e.cause.code : e.message));
    }
  }
  return null;
}

function dumpTail() {
  console.error("--- wrangler dev output (last lines) ---");
  for (const l of tail) console.error(l);
}

function stop() {
  if (WIN) spawnSync("taskkill", ["/pid", String(dev.pid), "/T", "/F"], { stdio: "ignore" });
  else dev.kill("SIGTERM");
}

(async () => {
  for (let i = 0; i < 60 && !ready; i++) await sleep(1000);
  if (!ready) {
    console.error("wrangler dev did not come up in 60 s");
    dumpTail();
    stop();
    process.exit(1);
  }
  await sleep(1500);
  const route = await trigger();
  if (!route) {
    console.error("the scheduled route answered neither /__scheduled nor /cdn-cgi/local/scheduled: " + statuses.join(", "));
    dumpTail();
    stop();
    process.exit(1);
  }
  console.log("documents cron triggered through " + route + " (" + keys.length + " offers, two calls each at most)");
  // Sonnet writes about 1 500 tokens per document, plus one possible retry: give it time.
  const deadline = Date.now() + keys.length * 90000 + 10000;
  let rows = [];
  while (Date.now() < deadline) {
    await sleep(5000);
    // The latest version per offer only: earlier ready rows must not mask this run.
    rows = d1("SELECT " + ROW_COLUMNS + " FROM documents WHERE job_key IN (" + keys.map(q).join(",") + ") AND id IN (SELECT MAX(id) FROM documents GROUP BY job_key) ORDER BY job_key");
    if (rows.every((r) => r.status === "ready" || r.status === "failed")) break;
  }
  stop();
  await sleep(1000);

  mkdirSync("private/out", { recursive: true });
  let total = 0;
  for (const r of rows) {
    const usd = r.cost_micro_usd / 1e6;
    total += usd;
    console.log(
      r.job_key + " v" + r.version + ": " + r.status + (r.error_code ? " (" + r.error_code + ")" : "") +
        ", attempts " + r.attempts + ", first attempt " + (r.first_errors === null ? "not reached" : r.first_errors === "[]" ? "passed" : "refused " + r.first_errors) +
        ", tokens in " + r.tokens_in + " / out " + r.tokens_out + ", " + usd.toFixed(4) + " $",
    );
    if (r.status === "ready" && r.content_key) await copyOut(r);
  }
  const after = d1("SELECT COALESCE(SUM(tokens_in), 0) AS tin, COALESCE(SUM(tokens_out), 0) AS tout FROM ai_usage WHERE model = 'claude-sonnet-5-5'")[0];
  const dIn = after.tin - before.tin;
  const dOut = after.tout - before.tout;
  console.log(
    "ai_usage (sonnet) this run: " + dIn + " tokens in, " + dOut + " out, " +
      ((dIn * PRICE_IN + dOut * PRICE_OUT) / 1e6).toFixed(4) + " $ at list price (cache reads cost less); documents total " + total.toFixed(4) + " $",
  );
  const history = d1("SELECT job_key, version, status, first_errors, attempts, cost_micro_usd FROM documents WHERE job_key IN (" + keys.map(q).join(",") + ") ORDER BY job_key, version");
  console.log("history: " + history.map((h) => h.job_key.split(":")[1] + " v" + h.version + " " + h.status + " first=" + (h.first_errors === null ? "?" : h.first_errors) + " attempts=" + h.attempts + " " + (h.cost_micro_usd / 1e6).toFixed(3) + "$").join(" | "));
  const run = d1("SELECT started_at, outcome, http_status, counters FROM document_runs ORDER BY id DESC LIMIT 1")[0];
  console.log("last document_runs row: " + JSON.stringify(run || null));
  const ok = rows.length === keys.length && rows.every((r) => r.status === "ready");
  console.log(ok ? "OK: " + rows.length + " documents ready" : "WARN: not every document is ready");
  process.exit(ok ? 0 : 1);
})();
