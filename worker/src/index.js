// job-match Worker. Everything outside /api/ is the static dashboard (served by the assets
// binding, behind Cloudflare Access). /api/ is the application-tracking API over D1:
//   GET  /api/applications       -> {applications, decisions, skill_overrides, ai_verdicts, ai_runs}
//   PUT  /api/applications/:key  -> {application}
//   POST /api/decisions          -> {decision}
//   DELETE /api/decisions/:id    -> {deleted}  (undo in the triage view)
//   PUT    /api/skill-overrides/:skill -> {skill_override}  ("je maîtrise", no body)
//   DELETE /api/skill-overrides/:skill -> {deleted}         (undo)
//   GET  /api/documents/:key             -> {documents: [versions]}   (ADR 0017)
//   POST /api/documents/:key/regenerate  -> {document}  (201, or 409 while one is pending)
//   GET  /api/documents/:key/v<n>/(cv|letter).(pdf|docx) -> the file, as an attachment
// Every API call needs a valid Access JWT and a same-origin request. JSON only, no CORS.
// Request bodies, notes and URLs are never logged. The crons (`scheduled`) run the AI rerank
// (ai.js, ADR 0016, twice a day) and the documents generation (documents.js, ADR 0017, every
// ten minutes) and log their counters only.

import { listRuns, listVerdicts, recordRun, runRerank } from "./ai.js";
import {
  DOCUMENTS_CRON,
  FILE_NAMES,
  fileKey,
  latestReadyVersion,
  listDocuments,
  listVersions,
  recordDocumentRun,
  requestDocuments,
  renderReady,
  requestFirstDocuments,
  runDocuments,
} from "./documents.js";
import { MIME } from "./render.js";
import { JwksUnavailable, verifyAccessJwt } from "./auth.js";
import { isJobKey, isSkill, validateApplication, validateDecision } from "./validate.js";

const MAX_BODY = 8 * 1024;
const BASE_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: BASE_HEADERS });
}

const fail = (status, error) => json(status, { error });

function sameOrigin(request, url) {
  const origin = request.headers.get("Origin");
  if (request.method === "GET") {
    if (origin !== null && origin !== url.origin) return false;
    return request.headers.get("Sec-Fetch-Site") !== "cross-site";
  }
  return origin === url.origin; // writes must say where they come from
}

async function readJson(request) {
  const type = request.headers.get("Content-Type") || "";
  if (!/^application\/json(\s*;|$)/i.test(type)) return { error: [415, "body: must be application/json"] };
  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > MAX_BODY) return { error: [413, "body: too large"] };
  const text = await request.text();
  if (text.length > MAX_BODY) return { error: [413, "body: too large"] };
  try {
    return { body: JSON.parse(text) };
  } catch {
    return { error: [400, "body: invalid JSON"] };
  }
}

async function listApplications(env) {
  const apps = await env.DB.prepare(
    "SELECT job_key, status, applied_at, follow_up_at, note, cv_url, updated_at" +
      " FROM applications ORDER BY updated_at DESC",
  ).all();
  // The latest verdict per job, enough for the dashboard to show it.
  const decisions = await env.DB.prepare(
    "SELECT job_key, label, created_at FROM decisions" +
      " WHERE id IN (SELECT MAX(id) FROM decisions GROUP BY job_key)",
  ).all();
  const overrides = await env.DB.prepare(
    "SELECT skill, created_at FROM skill_overrides ORDER BY skill",
  ).all();
  return json(200, {
    applications: apps.results,
    decisions: decisions.results,
    skill_overrides: overrides.results,
    ai_verdicts: await listVerdicts(env.DB),
    ai_runs: await listRuns(env.DB),
    documents: await listDocuments(env.DB),
  });
}

// Idempotent: marking a skill twice keeps the first date.
async function deleteDecision(env, id) {
  const row = await env.DB.prepare("DELETE FROM decisions WHERE id = ? RETURNING id").bind(id).first();
  return row ? json(200, { deleted: row.id }) : fail(404, "decision: not found");
}

async function putSkillOverride(env, skill) {
  const row = await env.DB.prepare(
    "INSERT INTO skill_overrides (skill, created_at) VALUES (?, ?)" +
      " ON CONFLICT(skill) DO UPDATE SET skill = excluded.skill" +
      " RETURNING skill, created_at",
  )
    .bind(skill, new Date().toISOString())
    .first();
  return json(200, { skill_override: row });
}

async function deleteSkillOverride(env, skill) {
  await env.DB.prepare("DELETE FROM skill_overrides WHERE skill = ?").bind(skill).run();
  return json(200, { deleted: skill });
}

async function putApplication(request, env, key) {
  const read = await readJson(request);
  if (read.error) return fail(...read.error);
  const checked = validateApplication(read.body);
  if (checked.error) return fail(400, checked.error);
  const a = checked.value;
  const row = await env.DB.prepare(
    "INSERT INTO applications (job_key, status, applied_at, follow_up_at, note, cv_url, updated_at)" +
      " VALUES (?, ?, ?, ?, ?, ?, ?)" +
      " ON CONFLICT(job_key) DO UPDATE SET status = excluded.status," +
      " applied_at = excluded.applied_at, follow_up_at = excluded.follow_up_at," +
      " note = excluded.note, cv_url = excluded.cv_url, updated_at = excluded.updated_at" +
      " RETURNING job_key, status, applied_at, follow_up_at, note, cv_url, updated_at",
  )
    .bind(key, a.status, a.applied_at, a.follow_up_at, a.note, a.cv_url, new Date().toISOString())
    .first();
  // "Garder" asks for the documents once; "Candidature envoyée" remembers which version went.
  const now = new Date();
  if (a.status === "to_apply") await requestFirstDocuments(env.DB, key, now);
  if (a.status === "applied") {
    const v = await latestReadyVersion(env.DB, key);
    if (v !== null) {
      await env.DB.prepare("UPDATE applications SET sent_documents_version = ? WHERE job_key = ?").bind(v, key).run();
    }
  }
  return json(200, { application: row });
}

// The file itself, from R2, as an attachment named after the contact and the company. The
// name was fixed at render time (R2 custom metadata), so nothing personal is read here.
async function downloadDocument(env, key, version, name) {
  const r2key = await fileKey(env.DB, key, version, name);
  const obj = r2key ? await env.DOCS.get(r2key) : null;
  if (!obj) return fail(404, "document: not found");
  const filename = (obj.customMetadata && obj.customMetadata.filename) || name;
  return new Response(obj.body, {
    status: 200,
    headers: {
      "Content-Type": MIME[name.split(".").pop()] || "application/octet-stream",
      "Content-Disposition": 'attachment; filename="' + filename.replace(/["\\]/g, "") + '"',
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function getDocuments(env, key) {
  return json(200, { documents: await listVersions(env.DB, key) });
}

async function regenerateDocuments(env, key) {
  const row = await requestDocuments(env.DB, key, new Date());
  return row ? json(201, { document: row }) : fail(409, "documents: already pending");
}

async function postDecision(request, env) {
  const read = await readJson(request);
  if (read.error) return fail(...read.error);
  const checked = validateDecision(read.body);
  if (checked.error) return fail(400, checked.error);
  const d = checked.value;
  const row = await env.DB.prepare(
    "INSERT INTO decisions (job_key, label, score_at_decision, created_at) VALUES (?, ?, ?, ?)" +
      " RETURNING id, job_key, label, score_at_decision, created_at",
  )
    .bind(d.job_key, d.label, d.score_at_decision, new Date().toISOString())
    .first();
  return json(201, { decision: row });
}

function decodeKey(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

async function route(request, env, url) {
  const path = url.pathname;
  if (path === "/api/applications") {
    return request.method === "GET" ? listApplications(env) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/applications/")) {
    const key = decodeKey(path.slice("/api/applications/".length));
    if (!isJobKey(key)) return fail(400, "job_key: invalid");
    return request.method === "PUT" ? putApplication(request, env, key) : fail(405, "method not allowed");
  }
  if (path === "/api/decisions") {
    return request.method === "POST" ? postDecision(request, env) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/decisions/")) {
    const raw = path.slice("/api/decisions/".length);
    if (!/^[1-9][0-9]{0,15}$/.test(raw)) return fail(400, "id: invalid");
    return request.method === "DELETE" ? deleteDecision(env, Number(raw)) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/documents/")) {
    const rest = path.slice("/api/documents/".length);
    const file = /^(.+)\/v([1-9][0-9]{0,5})\/(cv\.pdf|cv\.docx|letter\.pdf|letter\.docx)$/.exec(rest);
    if (file) {
      const key = decodeKey(file[1]);
      if (!isJobKey(key) || !FILE_NAMES.includes(file[3])) return fail(400, "job_key: invalid");
      if (!env.DOCS) return fail(500, "server misconfigured");
      return request.method === "GET" ? downloadDocument(env, key, Number(file[2]), file[3]) : fail(405, "method not allowed");
    }
    const regenerate = rest.endsWith("/regenerate");
    const key = decodeKey(regenerate ? rest.slice(0, -"/regenerate".length) : rest);
    if (!isJobKey(key)) return fail(400, "job_key: invalid");
    if (regenerate) return request.method === "POST" ? regenerateDocuments(env, key) : fail(405, "method not allowed");
    return request.method === "GET" ? getDocuments(env, key) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/skill-overrides/")) {
    const skill = decodeKey(path.slice("/api/skill-overrides/".length));
    if (!isSkill(skill)) return fail(400, "skill: invalid");
    if (request.method === "PUT") return putSkillOverride(env, skill);
    if (request.method === "DELETE") return deleteSkillOverride(env, skill);
    return fail(405, "method not allowed");
  }
  return fail(404, "not found");
}

export async function handleApi(request, env) {
  const url = new URL(request.url);
  if (!env.CF_ACCESS_AUD || !env.CF_ACCESS_TEAM_DOMAIN || !env.DB) {
    return fail(500, "server misconfigured");
  }
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return fail(401, "unauthenticated");
  let identity;
  try {
    identity = await verifyAccessJwt(token, {
      aud: env.CF_ACCESS_AUD,
      teamDomain: env.CF_ACCESS_TEAM_DOMAIN,
    });
  } catch (err) {
    if (err instanceof JwksUnavailable) return fail(503, "auth keys unavailable");
    return fail(401, "unauthenticated");
  }
  if (!identity) return fail(401, "unauthenticated");
  if (!sameOrigin(request, url)) return fail(403, "cross-origin request refused");
  try {
    return await route(request, env, url);
  } catch {
    return fail(500, "internal error"); // no detail: it could carry request data
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      return handleApi(request, env);
    }
    return env.ASSETS.fetch(request);
  },
  // After the daily run (wrangler.jsonc `triggers`, twice a day): judge the day's new offers.
  // The log carries counters and an HTTP status at most; the row in ai_runs the same.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(event && event.cron === DOCUMENTS_CRON ? runDocumentsScheduled(env) : runScheduled(env));
  },
};

// Every ten minutes: the pending documents, five at most. A pass with nothing to do leaves
// no trace; the others log one line of counters and write one document_runs row.
// The PDF font, bundled by wrangler as bytes (worker/src/fonts.js). Node cannot import it:
// the tests pass `opts.fonts` themselves, and without it nothing is rendered.
async function loadFonts() {
  try {
    return (await import("./fonts.js")).FONTS;
  } catch {
    return null;
  }
}

export async function runDocumentsScheduled(env, opts = {}) {
  const stamp = () => (opts.now || new Date()).toISOString();
  const startedAt = stamp();
  let run;
  try {
    run = await runDocuments(env, opts);
  } catch {
    run = { outcome: "failed", http_status: null, counters: {} };
  }
  // Part 3: the files of every ready version that has none yet, this pass's and earlier ones'.
  try {
    const fonts = opts.fonts === undefined ? await loadFonts() : opts.fonts;
    const rendered = await renderReady(env, { ...opts, fonts });
    if (rendered.rendered || rendered.render_errors) {
      run = { ...run, outcome: run.outcome === "idle" ? "ok" : run.outcome, counters: { ...run.counters, ...rendered } };
    }
  } catch {
    run = { ...run, counters: { ...run.counters, render_errors: 1 } };
  }
  if (run.outcome === "idle") return run;
  const status = run.http_status === null ? "" : " http=" + run.http_status;
  console.log("documents " + run.outcome + status + " " + JSON.stringify(run.counters));
  try {
    await recordDocumentRun(env.DB, startedAt, stamp(), run);
  } catch {
    console.log("documents: run row not written");
  }
  return run;
}

export async function runScheduled(env) {
  const startedAt = new Date().toISOString();
  let run;
  try {
    run = await runRerank(env);
  } catch {
    run = { outcome: "failed", http_status: null, provider: null, counters: {} };
  }
  const status = run.http_status === null ? "" : " http=" + run.http_status;
  console.log("ai rerank " + run.outcome + status + " " + JSON.stringify(run.counters));
  try {
    await recordRun(env.DB, startedAt, new Date().toISOString(), run);
  } catch {
    console.log("ai rerank: run row not written");
  }
  return run;
}
