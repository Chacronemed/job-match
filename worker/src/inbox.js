// Recruiter replies (ADR 0018, M27). n8n posts each email to POST /api/inbox; Haiku says what
// it is (entretien, refus, accusé de réception, relance, autre), how sure it is, which of my
// sent applications it answers and, for an interview, when. A sure interview or refusal
// updates the application; everything else waits for me in the dashboard (« à confirmer »).
// The email text never reaches D1 nor a log: this module has no `console` call, stores the
// sender's domain and a short subject, and the Worker logs counters only.
import { ANTHROPIC_MODEL, ANTHROPIC_URL, ANTHROPIC_VERSION, countCall, day, loadAsset } from "./ai.js";
import { INBOX_KINDS } from "./validate.js";

export const INBOX_MODEL = ANTHROPIC_MODEL; // Haiku, billed in ai_usage under this model
export const CONFIDENCE_THRESHOLD = 0.85;
export const INBOX_DAILY_LIMIT = 50; // the fallback; the wrangler var AI_INBOX_DAILY_LIMIT rules
export const INBOX_PROMPT_VERSION = "1";
const MAX_TOKENS = 400;
const AUTO_KINDS = new Set(["entretien", "refus"]);
const BILLED = new Set(["ok", "invalid", "refused"]);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const INBOX_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["type", "confidence", "interview_at", "application_key", "reason"],
  properties: {
    type: { type: "string", enum: INBOX_KINDS },
    confidence: { type: "number", minimum: 0, maximum: 1 },
    interview_at: { type: ["string", "null"], description: "YYYY-MM-DD when the email states the interview date, else null" },
    application_key: { type: ["string", "null"], description: "one of the listed keys, or null when no application matches" },
    reason: { type: "string", maxLength: 200 },
  },
};

const RULES = [
  "Tu classes un e-mail reçu par un candidat en recherche d'emploi (DevOps). Réponds en JSON strict.",
  "type : entretien (invitation ou proposition de créneau), refus (candidature non retenue),",
  "accuse_reception (simple confirmation de réception), relance_recruteur (le recruteur demande",
  "une action, des documents, une réponse), autre (newsletter, offre non sollicitée, hors sujet).",
  "confidence : ta certitude de 0 à 1 sur le type ET sur la candidature désignée ; sois prudent :",
  "au-dessus de 0,85 la candidature sera mise à jour sans relecture.",
  "application_key : la clé de la candidature concernée, choisie dans la liste par l'entreprise,",
  "le titre du poste et le domaine de l'expéditeur ; null si aucune ne correspond clairement.",
  "interview_at : la date de l'entretien au format YYYY-MM-DD si l'e-mail la donne, sinon null.",
  "N'invente rien : pas de clé hors liste, pas de date absente du texte.",
].join(" ");

// One cached system block: the rules and my sent applications (keys, companies, titles, dates).
// Sorted keys keep it byte-identical from one email to the next. Nothing personal in it.
export function buildInboxSystem(candidates) {
  const list = candidates.map((c) => ({
    application_key: c.key,
    company: c.company || null,
    sent_on: c.applied_at || null,
    title: c.title || null,
  }));
  const text = RULES + "\n\nCandidatures envoyées (JSON) :\n" + JSON.stringify(list);
  return [{ type: "text", text, cache_control: { type: "ephemeral" } }];
}

export function buildInboxUser(msg) {
  const domain = msg.sender_domain || "inconnu";
  const subject = msg.subject || "";
  return `<email domaine="${domain.replace(/"/g, "")}" sujet="${subject.replace(/"/g, "'")}">\n${msg.text}\n</email>`;
}

function isDay(value) {
  if (typeof value !== "string" || !DATE_RE.test(value)) return false;
  const d = new Date(value + "T00:00:00Z");
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

// The model's answer, or null: an unknown key, a bad date or an unknown type is "invalid".
export function validateInboxVerdict(obj, keys) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  const allowed = ["type", "confidence", "interview_at", "application_key", "reason"];
  if (Object.keys(obj).some((k) => !allowed.includes(k))) return null;
  if (!INBOX_KINDS.includes(obj.type)) return null;
  if (typeof obj.confidence !== "number" || !(obj.confidence >= 0 && obj.confidence <= 1)) return null;
  const key = obj.application_key === undefined ? null : obj.application_key;
  if (key !== null && (typeof key !== "string" || !keys.includes(key))) return null;
  const at = obj.interview_at === undefined ? null : obj.interview_at;
  if (at !== null && !isDay(at)) return null;
  if (obj.reason !== undefined && typeof obj.reason !== "string") return null;
  return { type: obj.type, confidence: obj.confidence, application_key: key, interview_at: at };
}

function parse(text, keys) {
  try {
    return validateInboxVerdict(JSON.parse(text), keys);
  } catch {
    return null;
  }
}

// One Claude call; the same outcomes as ai.js callAnthropic. The answer never leaves as text.
export async function callInbox(fetchFn, apiKey, system, user, keys) {
  const body = {
    model: INBOX_MODEL,
    max_tokens: MAX_TOKENS,
    system,
    messages: [{ role: "user", content: user }],
    output_config: { effort: "low", format: { type: "json_schema", schema: INBOX_SCHEMA } },
  };
  let res;
  try {
    res = await fetchFn(ANTHROPIC_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-api-key": apiKey, "anthropic-version": ANTHROPIC_VERSION },
      body: JSON.stringify(body),
    });
  } catch {
    return { verdict: null, outcome: "error", usage: { tokens_in: 0, tokens_out: 0 } };
  }
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }
  const u = (payload && payload.usage) || {};
  const usage = {
    tokens_in: (u.input_tokens | 0) + (u.cache_creation_input_tokens | 0) + (u.cache_read_input_tokens | 0),
    tokens_out: u.output_tokens | 0,
  };
  if (res.status === 402) return { verdict: null, outcome: "credit", usage };
  if (res.status === 429) return { verdict: null, outcome: "rate_limited", usage };
  if (res.status >= 400 && res.status < 500 && res.status !== 408) return { verdict: null, outcome: "client_error", status: res.status, usage };
  if (res.status !== 200 || !payload) return { verdict: null, outcome: "error", usage };
  if (payload.stop_reason === "refusal") return { verdict: null, outcome: "refused", usage };
  const block = Array.isArray(payload.content) ? payload.content.find((b) => b && b.type === "text") : null;
  const verdict = block ? parse(block.text, keys) : null;
  return { verdict, outcome: verdict ? "ok" : "invalid", usage };
}

// The offers of data.json (listed and tracked) by key: title, company, url.
function offersByKey(data) {
  const out = new Map();
  for (const list of [data && data.jobs, data && data.tracked]) {
    if (!Array.isArray(list)) continue;
    for (const j of list) if (j && typeof j.key === "string" && !out.has(j.key)) out.set(j.key, j);
  }
  return out;
}

// My sent applications (« Envoyée » = status applied), with what the offers say about them.
export async function appliedCandidates(db, data) {
  const rows = await db.prepare("SELECT job_key, applied_at FROM applications WHERE status = 'applied' ORDER BY applied_at DESC, job_key").all();
  const offers = offersByKey(data);
  return rows.results.map((r) => {
    const j = offers.get(r.job_key) || {};
    return { key: r.job_key, title: j.title || null, company: j.company || null, applied_at: r.applied_at || null };
  });
}

// What a confirmed reply does to the application. An interview moves it to « Entretien » with
// its date and drops the pending follow-up; a refusal moves it to « Refus ». Other kinds
// change nothing. Returns the row after, or null when the application is gone.
export async function applyVerdict(db, key, kind, interviewAt, now) {
  const stamp = now.toISOString();
  if (kind === "entretien") {
    await db
      .prepare("UPDATE applications SET status = 'interview', interview_at = COALESCE(?, interview_at), follow_up_at = NULL, updated_at = ? WHERE job_key = ?")
      .bind(interviewAt || null, stamp, key)
      .run();
  } else if (kind === "refus") {
    await db.prepare("UPDATE applications SET status = 'rejected', follow_up_at = NULL, updated_at = ? WHERE job_key = ?").bind(stamp, key).run();
  }
  return db
    .prepare("SELECT job_key, status, applied_at, follow_up_at, interview_at, note, cv_url, updated_at, sent_documents_version FROM applications WHERE job_key = ?")
    .bind(key)
    .first();
}

function dailyLimit(env, opts) {
  if (Number.isInteger(opts.limit)) return opts.limit;
  const fromEnv = Number(env.AI_INBOX_DAILY_LIMIT);
  return Number.isInteger(fromEnv) && fromEnv > 0 ? fromEnv : INBOX_DAILY_LIMIT;
}

async function callsToday(db, today) {
  const row = await db
    .prepare("SELECT COUNT(*) AS n FROM inbox_items WHERE substr(created_at, 1, 10) = ? AND ai_outcome IN ('ok', 'invalid', 'refused')")
    .bind(today)
    .first();
  return row ? row.n | 0 : 0;
}

// One email. Returns {status, body} for the route: 200 when the id was seen (nothing redone),
// 201 otherwise, with the state and the verdict (never the text). `opts.fetch`, `opts.now`,
// `opts.limit` serve the tests.
export async function handleInbox(env, msg, opts = {}) {
  const db = env.DB;
  const now = opts.now || new Date();
  const fetchFn = opts.fetch || globalThis.fetch;
  const seen = await db.prepare("SELECT state, kind, confidence, proposed_key FROM inbox_items WHERE message_id = ?").bind(msg.message_id).first();
  if (seen) return { status: 200, body: { message_id: msg.message_id, duplicate: true, state: seen.state, kind: seen.kind, confidence: seen.confidence, proposed_key: seen.proposed_key } };

  const data = await loadAsset(env, "/data.json");
  const candidates = await appliedCandidates(db, data);
  const keys = candidates.map((c) => c.key);
  let verdict = null;
  let outcome = "skipped_none";
  if (keys.length && env.ANTHROPIC_API_KEY) {
    const today = day(now);
    if ((await callsToday(db, today)) >= dailyLimit(env, opts)) {
      outcome = "skipped_cap";
    } else {
      const call = await callInbox(fetchFn, env.ANTHROPIC_API_KEY, buildInboxSystem(candidates), buildInboxUser(msg), keys);
      outcome = call.outcome;
      verdict = call.verdict;
      if (BILLED.has(call.outcome)) await countCall(db, today, "anthropic", INBOX_MODEL, call.usage);
    }
  } else if (keys.length) {
    outcome = "no_key";
  }

  const auto = verdict && verdict.confidence >= CONFIDENCE_THRESHOLD && AUTO_KINDS.has(verdict.type) && verdict.application_key !== null;
  let state = "to_confirm";
  let application = null;
  if (auto) {
    application = await applyVerdict(db, verdict.application_key, verdict.type, verdict.interview_at, now);
    if (application) state = "applied";
  }
  const stamp = now.toISOString();
  await db
    .prepare(
      "INSERT INTO inbox_items (message_id, received_at, sender_domain, subject, kind, confidence, interview_at," +
        " proposed_key, state, applied_key, applied_at, ai_outcome, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(
      msg.message_id,
      msg.received_at || stamp,
      msg.sender_domain,
      msg.subject,
      verdict ? verdict.type : null,
      verdict ? verdict.confidence : null,
      verdict ? verdict.interview_at : null,
      verdict ? verdict.application_key : null,
      state,
      state === "applied" ? verdict.application_key : null,
      state === "applied" ? stamp : null,
      outcome,
      stamp,
    )
    .run();
  return {
    status: 201,
    body: {
      message_id: msg.message_id,
      state,
      kind: verdict ? verdict.type : null,
      confidence: verdict ? verdict.confidence : null,
      proposed_key: verdict ? verdict.application_key : null,
      ai: outcome,
    },
  };
}

// The sent applications whose follow-up is due today or earlier, oldest first, with what the
// offers say (null when the offer left data.json).
export async function listFollowupsDue(db, data, today) {
  const rows = await db
    .prepare("SELECT job_key, applied_at, follow_up_at FROM applications WHERE status = 'applied' AND follow_up_at IS NOT NULL AND follow_up_at <= ? ORDER BY follow_up_at, job_key")
    .bind(today)
    .all();
  const offers = offersByKey(data);
  return rows.results.map((r) => {
    const j = offers.get(r.job_key) || {};
    return {
      key: r.job_key,
      title: j.title || null,
      company: j.company || null,
      url: typeof j.url === "string" ? j.url : null,
      applied_at: r.applied_at,
      follow_up_at: r.follow_up_at,
    };
  });
}

const ITEM_COLUMNS = "message_id, received_at, sender_domain, subject, kind, confidence, interview_at, proposed_key, state, applied_key, applied_at, ai_outcome";

// For the dashboard: the parked replies, newest first, and the recent handled ones.
export async function listInbox(db, historyLimit = 100) {
  const toConfirm = await db.prepare(`SELECT ${ITEM_COLUMNS} FROM inbox_items WHERE state = 'to_confirm' ORDER BY received_at DESC`).all();
  const history = await db
    .prepare(`SELECT ${ITEM_COLUMNS} FROM inbox_items WHERE state != 'to_confirm' ORDER BY COALESCE(applied_at, received_at) DESC LIMIT ?`)
    .bind(historyLimit)
    .all();
  return { to_confirm: toConfirm.results, history: history.results };
}

// Valider / Corriger / Ignorer. Returns {status, body}: 404 unknown id, 409 already handled,
// 400 when confirm has nothing to confirm (no kind or, for entretien/refus, no key).
export async function actOnInbox(db, messageId, act, now) {
  const item = await db.prepare(`SELECT ${ITEM_COLUMNS} FROM inbox_items WHERE message_id = ?`).bind(messageId).first();
  if (!item) return { status: 404, body: { error: "inbox: not found" } };
  if (item.state !== "to_confirm") return { status: 409, body: { error: "inbox: already handled" } };
  const stamp = now.toISOString();
  let kind = item.kind;
  let key = item.proposed_key;
  let interviewAt = item.interview_at;
  let state = "ignored";
  if (act.action === "confirm") {
    if (!kind) return { status: 400, body: { error: "confirm: nothing to confirm" } };
    if (act.application_key !== null) key = act.application_key;
    if (act.interview_at !== null) interviewAt = act.interview_at;
    if (AUTO_KINDS.has(kind) && !key) return { status: 400, body: { error: "confirm: application_key required" } };
    state = "applied";
  } else if (act.action === "correct") {
    kind = act.kind;
    key = act.application_key;
    interviewAt = act.interview_at;
    state = "corrected";
  }
  let application = null;
  if (state !== "ignored" && key && AUTO_KINDS.has(kind)) {
    application = await applyVerdict(db, key, kind, interviewAt, now);
    if (!application) return { status: 404, body: { error: "application: not found" } };
  }
  await db
    .prepare("UPDATE inbox_items SET state = ?, kind = ?, interview_at = ?, applied_key = ?, applied_at = ? WHERE message_id = ?")
    .bind(state, kind, interviewAt, state === "ignored" ? null : key, stamp, messageId)
    .run();
  const row = await db.prepare(`SELECT ${ITEM_COLUMNS} FROM inbox_items WHERE message_id = ?`).bind(messageId).first();
  return { status: 200, body: { item: row, application } };
}
