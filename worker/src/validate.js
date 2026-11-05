// Field rules for the tracking API. The Python mirror (src/job_match/tracking/mirror.py)
// applies the same rules to the rows it imports; tests check both lists of values agree.

export const STATUSES = ["to_review", "to_apply", "applied", "interview", "rejected", "ignored"];
export const LABELS = ["good_fit", "off_topic", "too_senior", "missing_skill", "location"];
export const NOTE_MAX = 2000;
export const URL_MAX = 500;

export const SKILL_MAX = 40;

const JOB_KEY_RE = /^[a-z0-9_]{1,32}:[A-Za-z0-9._:-]{1,128}$/;
// A vocabulary term, lowercase: "gitlab ci", "c#", "node.js".
const SKILL_RE = /^[a-z0-9][a-z0-9+#./ -]{0,39}$/;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const APPLICATION_FIELDS = ["status", "applied_at", "follow_up_at", "interview_at", "note", "cv_url"];
// Recruiter replies (ADR 0018): what n8n posts, and what the dashboard does with a parked one.
export const INBOX_KINDS = ["entretien", "refus", "accuse_reception", "relance_recruteur", "autre"];
export const INBOX_ACTIONS = ["confirm", "correct", "ignore"];
const INBOX_FIELDS = ["message_id", "from", "subject", "date", "text"];
const INBOX_ACTION_FIELDS = ["action", "application_key", "kind", "interview_at"];
export const MESSAGE_ID_MAX = 200;
export const SUBJECT_MAX = 200;
export const INBOX_TEXT_MAX = 4000;
const DECISION_FIELDS = ["job_key", "label", "score_at_decision"];

export function isJobKey(value) {
  return typeof value === "string" && JOB_KEY_RE.test(value);
}

export function isSkill(value) {
  return typeof value === "string" && value.length <= SKILL_MAX && SKILL_RE.test(value);
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function unknownField(body, allowed) {
  return Object.keys(body).find((k) => !allowed.includes(k));
}

// "" from an empty form field means "no value".
function blankToNull(value) {
  return value === undefined || value === "" ? null : value;
}

function checkDate(value) {
  if (value === null) return true;
  if (typeof value !== "string") return false;
  const m = DATE_RE.exec(value);
  if (!m) return false;
  const year = Number(m[1]);
  if (year < 2000 || year > 2100) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

function checkHttpsUrl(value) {
  if (value === null) return true;
  if (typeof value !== "string" || value.length > URL_MAX) return false;
  let url;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  return url.protocol === "https:" && url.hostname !== "" && !url.username && !url.password;
}

// Returns {value} with every field present (null when empty) or {error: "<field>: <rule>"}.
// Errors never repeat the submitted value.
export function validateApplication(body) {
  if (!isPlainObject(body)) return { error: "body: must be a JSON object" };
  const extra = unknownField(body, APPLICATION_FIELDS);
  if (extra !== undefined) return { error: "body: unknown field" };
  const value = {
    status: body.status,
    applied_at: blankToNull(body.applied_at),
    follow_up_at: blankToNull(body.follow_up_at),
    interview_at: blankToNull(body.interview_at),
    note: blankToNull(body.note),
    cv_url: blankToNull(body.cv_url),
  };
  if (!STATUSES.includes(value.status)) return { error: "status: not an allowed value" };
  if (!checkDate(value.applied_at)) return { error: "applied_at: must be YYYY-MM-DD" };
  if (!checkDate(value.follow_up_at)) return { error: "follow_up_at: must be YYYY-MM-DD" };
  if (!checkDate(value.interview_at)) return { error: "interview_at: must be YYYY-MM-DD" };
  if (value.note !== null && (typeof value.note !== "string" || value.note.length > NOTE_MAX)) {
    return { error: `note: must be text of at most ${NOTE_MAX} characters` };
  }
  if (!checkHttpsUrl(value.cv_url)) return { error: "cv_url: must be an https URL" };
  return { value };
}

export function validateDecision(body) {
  if (!isPlainObject(body)) return { error: "body: must be a JSON object" };
  if (unknownField(body, DECISION_FIELDS) !== undefined) return { error: "body: unknown field" };
  const score = body.score_at_decision === undefined ? null : body.score_at_decision;
  if (!isJobKey(body.job_key)) return { error: "job_key: invalid" };
  if (!LABELS.includes(body.label)) return { error: "label: not an allowed value" };
  if (score !== null && !(Number.isInteger(score) && score >= 0 && score <= 100)) {
    return { error: "score_at_decision: must be an integer 0-100 or null" };
  }
  return { value: { job_key: body.job_key, label: body.label, score_at_decision: score } };
}

export function isMessageId(value) {
  return typeof value === "string" && value.length >= 1 && value.length <= MESSAGE_ID_MAX && !/[\s]/.test(value);
}

// The email as n8n posts it. The text is cut to INBOX_TEXT_MAX here, the subject to
// SUBJECT_MAX; only the sender's domain is kept. Errors never repeat a value.
export function validateInboxMessage(body) {
  if (!isPlainObject(body)) return { error: "body: must be a JSON object" };
  if (unknownField(body, INBOX_FIELDS) !== undefined) return { error: "body: unknown field" };
  if (!isMessageId(body.message_id)) return { error: "message_id: invalid" };
  const from = blankToNull(body.from);
  if (from !== null && (typeof from !== "string" || from.length > 320)) return { error: "from: invalid" };
  const subject = blankToNull(body.subject);
  if (subject !== null && typeof subject !== "string") return { error: "subject: must be text" };
  const date = blankToNull(body.date);
  if (date !== null && (typeof date !== "string" || Number.isNaN(Date.parse(date)))) {
    return { error: "date: must be an ISO date" };
  }
  if (typeof body.text !== "string") return { error: "text: must be text" };
  const at = from === null ? -1 : from.lastIndexOf("@");
  const domain = at < 0 ? null : from.slice(at + 1).replace(/[>\s"'].*$/, "").toLowerCase() || null;
  return {
    value: {
      message_id: body.message_id,
      sender_domain: domain,
      subject: subject === null ? null : subject.slice(0, SUBJECT_MAX),
      received_at: date === null ? null : new Date(date).toISOString(),
      text: body.text.slice(0, INBOX_TEXT_MAX),
    },
  };
}

// Valider / Corriger / Ignorer on a parked reply.
export function validateInboxAction(body) {
  if (!isPlainObject(body)) return { error: "body: must be a JSON object" };
  if (unknownField(body, INBOX_ACTION_FIELDS) !== undefined) return { error: "body: unknown field" };
  if (!INBOX_ACTIONS.includes(body.action)) return { error: "action: not an allowed value" };
  const value = {
    action: body.action,
    application_key: blankToNull(body.application_key),
    kind: blankToNull(body.kind),
    interview_at: blankToNull(body.interview_at),
  };
  if (value.application_key !== null && !isJobKey(value.application_key)) return { error: "application_key: invalid" };
  if (value.kind !== null && !INBOX_KINDS.includes(value.kind)) return { error: "kind: not an allowed value" };
  if (!checkDate(value.interview_at)) return { error: "interview_at: must be YYYY-MM-DD" };
  if (value.action === "correct" && (value.application_key === null || value.kind === null)) {
    return { error: "correct: needs application_key and kind" };
  }
  return { value };
}
