// job-match Worker. Everything outside /api/ is the static dashboard (served by the assets
// binding, behind Cloudflare Access). /api/ is the application-tracking API over D1:
//   GET  /api/applications       -> {applications, decisions, skill_overrides, ai_verdicts, ai_runs,
//                                    documents, documents_budget}
//   PUT  /api/applications/:key  -> {application}
//   POST /api/applications/:key/reactivate -> {application}  (« Réactiver » an auto-archived
//                                   « À candidater » application, ADR 0028: reactivated_at = now)
//   POST /api/decisions          -> {decision}
//   DELETE /api/decisions/:id    -> {deleted}  (undo in the triage view)
//   PUT    /api/skill-overrides/:skill -> {skill_override}  ("je maîtrise", no body)
//   DELETE /api/skill-overrides/:skill -> {deleted}         (undo)
//   GET  /api/documents/:key             -> {documents: [versions]}   (ADR 0017)
//   POST /api/documents/:key/regenerate  -> {document}  (201, or 409 while one is pending);
//                                           the pass for that offer runs now (ctx.waitUntil)
//   GET  /api/documents/:key/v<n>/content.json -> {content, master, contact}: what the browser
//                                           renders the PDF and the DOCX from (ADR 0019)
//   POST /api/ai/run         -> 202 {started, kind}  (the rerank pass, now, in the background)
//   POST /api/documents/run  -> 202 {started, kind}  (the documents pass, now, in the background)
//   POST /api/documents/missing -> {requested, skipped_budget, remaining_usd, documents}
//                               (a pending row per kept offer without one, within the budget)
//   POST /api/inbox              -> 201 {message_id, state, kind, confidence, proposed_key, ai}
//                                   (a recruiter email from n8n, classified by Haiku; ADR 0018)
//   GET  /api/followups/due      -> {today, due: [{key, title, company, url, applied_at, follow_up_at}]}
//   PUT  /api/inbox/:message_id  -> {item, application}  (Valider / Corriger / Ignorer)
// Every API call needs a valid Access JWT: my login (an `email` claim) everywhere, or the Access
// service token whose Client ID is the ACCESS_SERVICE_CN secret (the `common_name` claim) on
// /api/inbox and /api/followups/due only. Browser calls must be same-origin; JSON only, no CORS.
// Request bodies, notes and URLs are never logged. The crons (`scheduled`) run the AI rerank
// (ai.js, ADR 0016, twice a day) and the documents generation (documents.js, ADR 0017, every
// ten minutes) and log their counters only.

import { listRuns, listVerdicts, recordRun, runRerank } from "./ai.js";
import {
  budgetStatus,
  DOCUMENTS_CRON,
  latestReadyVersion,
  listDocuments,
  listVersions,
  loadBundle,
  recordDocumentRun,
  requestDocuments,
  requestFirstDocuments,
  requestMissingDocuments,
  runDocuments,
} from "./documents.js";
import { actOnInbox, handleInbox, listFollowupsDue, listInbox } from "./inbox.js";
import { day, loadAsset } from "./ai.js";
import { JwksUnavailable, principalOf, verifyAccessJwt } from "./auth.js";
import {
  isJobKey,
  isMessageId,
  isSkill,
  validateApplication,
  validateDecision,
  validateInboxAction,
  validateInboxMessage,
} from "./validate.js";

const MAX_BODY = 8 * 1024;
const APP_COLUMNS =
  "job_key, status, applied_at, follow_up_at, interview_at, note, cv_url, updated_at, sent_documents_version, reactivated_at";
const INBOX_MAX_BODY = 64 * 1024; // an email, cut to 4 000 characters before the model anyway
// The routes a service token may call (ADR 0018); everything else is mine alone.
const SERVICE_ROUTES = new Set(["/api/inbox", "/api/followups/due"]);
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

async function readJson(request, limit = MAX_BODY) {
  const type = request.headers.get("Content-Type") || "";
  if (!/^application\/json(\s*;|$)/i.test(type)) return { error: [415, "body: must be application/json"] };
  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > limit) return { error: [413, "body: too large"] };
  const text = await request.text();
  if (text.length > limit) return { error: [413, "body: too large"] };
  try {
    return { body: JSON.parse(text) };
  } catch {
    return { error: [400, "body: invalid JSON"] };
  }
}

async function listApplications(env) {
  const apps = await env.DB.prepare("SELECT " + APP_COLUMNS + " FROM applications ORDER BY updated_at DESC").all();
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
    documents_budget: await budgetStatus(env.DB, env, new Date()),
    inbox: await listInbox(env.DB),
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
    "INSERT INTO applications (job_key, status, applied_at, follow_up_at, interview_at, note, cv_url, updated_at)" +
      " VALUES (?, ?, ?, ?, ?, ?, ?, ?)" +
      " ON CONFLICT(job_key) DO UPDATE SET status = excluded.status," +
      " applied_at = excluded.applied_at, follow_up_at = excluded.follow_up_at," +
      " interview_at = excluded.interview_at," +
      " note = excluded.note, cv_url = excluded.cv_url, updated_at = excluded.updated_at" +
      " RETURNING " + APP_COLUMNS,
  )
    .bind(key, a.status, a.applied_at, a.follow_up_at, a.interview_at, a.note, a.cv_url, new Date().toISOString())
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

// « Réactiver » (ADR 0028): an auto-archived « À candidater » application comes back for
// another KEPT_DAYS from today; the published-age rule no longer applies to it. The archive
// itself is never stored, so this is the only write: the date, and updated_at with it.
async function reactivateApplication(env, key) {
  const current = await env.DB.prepare("SELECT status FROM applications WHERE job_key = ?").bind(key).first();
  if (!current) return fail(404, "application: not found");
  if (current.status !== "to_apply") return fail(409, "application: not « À candidater »");
  const now = new Date().toISOString();
  const row = await env.DB.prepare(
    "UPDATE applications SET reactivated_at = ?, updated_at = ? WHERE job_key = ? RETURNING " + APP_COLUMNS,
  )
    .bind(now, now, key)
    .first();
  return json(200, { application: row });
}

// What the browser renders from (ADR 0019): the content, the master and the contact sheet of
// one ready version. The contact details travel to my own browser behind Access, never to a
// log or a model. `no-store`: the file is private and the version may be regenerated.
async function getContent(env, key, version) {
  const bundle = await loadBundle(env, key, version);
  if (!bundle) return fail(404, "document: not found");
  return new Response(JSON.stringify(bundle), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}

async function getDocuments(env, key) {
  return json(200, { documents: await listVersions(env.DB, key) });
}

// « Générer » / « Regénérer »: the new pending row, and the pass for that offer right away
// (same budget and credit rules as the cron, its own document_runs row). Without a ctx (the
// Node tests) the row waits for the cron.
async function regenerateDocuments(env, key, ctx) {
  const row = await requestDocuments(env.DB, key, new Date());
  if (!row) return fail(409, "documents: already pending");
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(runDocumentsScheduled(env, { keys: [key] }));
  return json(201, { document: row });
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

// n8n's email (ADR 0018): validated, cut, classified, stored without its text. The log line
// carries the state and the AI outcome only.
async function postInbox(request, env) {
  const read = await readJson(request, INBOX_MAX_BODY);
  if (read.error) return fail(...read.error);
  const checked = validateInboxMessage(read.body);
  if (checked.error) return fail(400, checked.error);
  const out = await handleInbox(env, checked.value);
  if (out.status === 201) console.log("inbox " + out.body.state + " kind=" + (out.body.kind || "none") + " ai=" + out.body.ai);
  return json(out.status, out.body);
}

async function getFollowupsDue(env) {
  const today = day(new Date());
  return json(200, { today, due: await listFollowupsDue(env.DB, await loadAsset(env, "/data.json"), today) });
}

async function putInbox(request, env, id) {
  const read = await readJson(request);
  if (read.error) return fail(...read.error);
  const checked = validateInboxAction(read.body);
  if (checked.error) return fail(400, checked.error);
  const out = await actOnInbox(env.DB, id, checked.value, new Date());
  return json(out.status, out.body);
}

function decodeKey(segment) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

async function route(request, env, url, ctx) {
  const path = url.pathname;
  // « Lancer maintenant »: the same passes as the crons, started here, finished after the
  // response (ctx.waitUntil). Their row in ai_runs / document_runs is the report.
  if (path === "/api/ai/run" || path === "/api/documents/run") {
    if (request.method !== "POST") return fail(405, "method not allowed");
    const kind = path === "/api/ai/run" ? "ai" : "documents";
    const pass = kind === "ai" ? runScheduled(env) : runDocumentsScheduled(env);
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(pass); else pass.catch(() => {});
    return json(202, { started: true, kind });
  }
  if (path === "/api/inbox") {
    return request.method === "POST" ? postInbox(request, env) : fail(405, "method not allowed");
  }
  if (path === "/api/followups/due") {
    return request.method === "GET" ? getFollowupsDue(env) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/inbox/")) {
    const id = decodeKey(path.slice("/api/inbox/".length));
    if (!isMessageId(id)) return fail(400, "message_id: invalid");
    return request.method === "PUT" ? putInbox(request, env, id) : fail(405, "method not allowed");
  }
  if (path === "/api/documents/missing") {
    if (request.method !== "POST") return fail(405, "method not allowed");
    return json(200, await requestMissingDocuments(env.DB, env, new Date()));
  }
  if (path === "/api/applications") {
    return request.method === "GET" ? listApplications(env) : fail(405, "method not allowed");
  }
  if (path.startsWith("/api/applications/")) {
    const rest = path.slice("/api/applications/".length);
    const reactivate = rest.endsWith("/reactivate");
    const key = decodeKey(reactivate ? rest.slice(0, -"/reactivate".length) : rest);
    if (!isJobKey(key)) return fail(400, "job_key: invalid");
    if (reactivate) return request.method === "POST" ? reactivateApplication(env, key) : fail(405, "method not allowed");
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
    const file = /^(.+)\/v([1-9][0-9]{0,5})\/content\.json$/.exec(rest);
    if (file) {
      const key = decodeKey(file[1]);
      if (!isJobKey(key)) return fail(400, "job_key: invalid");
      if (!env.DOCS) return fail(500, "server misconfigured");
      return request.method === "GET" ? getContent(env, key, Number(file[2])) : fail(405, "method not allowed");
    }
    const regenerate = rest.endsWith("/regenerate");
    const key = decodeKey(regenerate ? rest.slice(0, -"/regenerate".length) : rest);
    if (!isJobKey(key)) return fail(400, "job_key: invalid");
    if (regenerate) return request.method === "POST" ? regenerateDocuments(env, key, ctx) : fail(405, "method not allowed");
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

export async function handleApi(request, env, ctx) {
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
  const who = principalOf(identity, env);
  if (!who) return fail(401, "unauthenticated");
  // A machine (n8n) reaches two routes and sends no Origin; a browser must be same-origin.
  if (who.kind === "service" && !SERVICE_ROUTES.has(url.pathname)) return fail(403, "service token: route not allowed");
  if (who.kind === "user" && !sameOrigin(request, url)) return fail(403, "cross-origin request refused");
  try {
    return await route(request, env, url, ctx);
  } catch {
    return fail(500, "internal error"); // no detail: it could carry request data
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      return handleApi(request, env, ctx);
    }
    return env.ASSETS.fetch(request);
  },
  // After the daily run (wrangler.jsonc `triggers`, twice a day): judge the day's new offers.
  // The log carries counters and an HTTP status at most; the row in ai_runs the same.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(event && event.cron === DOCUMENTS_CRON ? runDocumentsScheduled(env) : runScheduled(env));
  },
};

// Every ten minutes: the « À candidater » offers without documents are queued, then the
// pending documents run, five at most. A pass with nothing to do leaves no trace; the others
// log one line of counters and write one document_runs row. `opts.keys` limits a pass to
// those offers (« Générer »).
export async function runDocumentsScheduled(env, opts = {}) {
  const stamp = () => (opts.now || new Date()).toISOString();
  const startedAt = stamp();
  let run;
  try {
    run = await runDocuments(env, opts);
  } catch {
    run = { outcome: "failed", http_status: null, counters: {} };
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
