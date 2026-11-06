// Auto-archive rule (ADR 0028), pure, shared by the Worker (documents.js) and checked against
// the page's copy (src/job_match/dashboard/assets/tracking.js, `archiveState`) by a Node test.
// An « À candidater » application nobody handled leaves the lists by itself, never deleted:
//   - kept more than KEPT_DAYS ago without being sent. The kept day is the « Réactiver » date
//     when there is one (it restarts the counter and switches the published rule off), else
//     the « Garder » decision (the latest decision, when it is good_fit); no decision, no kept rule;
//   - or the offer published more than PUBLISHED_DAYS ago (unknown publication: kept rule only).
// « Expirée » (the offer closed) wins: an expired application is never archived.
// config/settings.yaml `archive:` repeats the two values; a Python test keeps them equal.

export const KEPT_DAYS = 15;
export const PUBLISHED_DAYS = 20;
export const ARCHIVE = { kept_days: KEPT_DAYS, published_days: PUBLISHED_DAYS };

const DAY = /^(\d{4})-(\d{2})-(\d{2})/;

// The calendar day (YYYY-MM-DD) of an ISO timestamp or date; null when unreadable.
export function dayOf(value) {
  const m = typeof value === "string" ? DAY.exec(value) : null;
  if (!m) return null;
  const day = m[0];
  const d = new Date(day + "T00:00:00Z");
  return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === day ? day : null;
}

export function daysBetween(fromDay, toDay) {
  return Math.round((Date.parse(toDay + "T00:00:00Z") - Date.parse(fromDay + "T00:00:00Z")) / 86400000);
}

// `decision`: {label, created_at} of the application's latest decision, or null.
export function keptDay(app, decision) {
  const reactivated = dayOf(app && app.reactivated_at);
  if (reactivated) return reactivated;
  return decision && decision.label === "good_fit" ? dayOf(decision.created_at) : null;
}

// null, or {reason: "kept" | "published", days}.
export function archiveState(app, posting, decision, today, cfg = ARCHIVE) {
  if (!app || app.status !== "to_apply") return null;
  if (posting && posting.closed === true) return null; // « Expirée » wins
  const kept = keptDay(app, decision);
  if (kept) {
    const days = daysBetween(kept, today);
    if (days > cfg.kept_days) return { reason: "kept", days };
  }
  if (!dayOf(app.reactivated_at)) {
    const published = dayOf(posting && posting.published_at);
    if (published) {
      const days = daysBetween(published, today);
      if (days > cfg.published_days) return { reason: "published", days };
    }
  }
  return null;
}

export function isArchived(app, posting, decision, today, cfg) {
  return archiveState(app, posting, decision, today, cfg) !== null;
}

// « gardée il y a 17 jours » / « publiée il y a 23 jours ».
export function archiveReason(state) {
  if (!state) return "";
  const verb = state.reason === "kept" ? "gardée" : "publiée";
  return verb + " il y a " + state.days + " jour" + (state.days !== 1 ? "s" : "");
}

// The latest decision per job_key, as the Worker reads it from D1.
export function decisionIndex(rows) {
  const index = new Map();
  for (const r of rows || []) {
    if (r && typeof r.job_key === "string") index.set(r.job_key, { label: r.label, created_at: r.created_at });
  }
  return index;
}
