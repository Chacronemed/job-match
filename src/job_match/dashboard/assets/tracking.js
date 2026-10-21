/* job-match application tracking: the logic the dashboard shares with its tests. No DOM
   here. The statuses and labels match the D1 schema (worker/migrations/0001_tracking.sql),
   the Worker and src/job_match/tracking/constants.py; a test checks they agree. */
(function (root) {
  "use strict";

  var STATUSES = ["to_review", "to_apply", "applied", "interview", "rejected", "ignored"];
  var STATUS_TEXT = {
    to_review: "À examiner",
    to_apply: "À candidater",
    applied: "Candidature envoyée",
    interview: "Entretien",
    rejected: "Refusée",
    ignored: "Ignorée"
  };
  var LABELS = ["good_fit", "off_topic", "too_senior", "missing_skill", "location"];
  var LABEL_TEXT = {
    good_fit: "Bon match",
    off_topic: "Hors sujet",
    too_senior: "Trop senior",
    missing_skill: "Compétence manquante",
    location: "Lieu"
  };
  /* How far an application got: a grouped row shows its most advanced posting. */
  var STATUS_RANK = { ignored: 0, to_review: 1, to_apply: 2, applied: 3, interview: 4, rejected: 5 };
  var ACTIVE = ["to_review", "to_apply"];
  var NO_FOLLOW_UP = ["rejected", "ignored"];
  var NOTE_MAX = 2000;
  var URL_MAX = 500;
  var DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

  /* A job with no tracking row is still waiting for a first look. */
  function statusOf(app) {
    return app && STATUSES.indexOf(app.status) >= 0 ? app.status : "to_review";
  }

  function isActive(status) {
    return ACTIVE.indexOf(status) >= 0;
  }

  function isDay(value) {
    var m = typeof value === "string" ? DAY.exec(value) : null;
    if (!m) return false;
    var d = new Date(value + "T00:00:00Z");
    return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
  }

  /* Today in the viewer's own calendar, as YYYY-MM-DD. */
  function localDay(now) {
    var d = now || new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate());
  }

  function daysBetween(fromDay, toDay) {
    return Math.round((Date.parse(toDay + "T00:00:00Z") - Date.parse(fromDay + "T00:00:00Z")) / 86400000);
  }

  function isDue(app, today) {
    return !!app && isDay(app.follow_up_at) && app.follow_up_at <= today &&
      NO_FOLLOW_UP.indexOf(app.status) < 0;
  }

  /* The postings a row stands for: itself, or every posting of its group. */
  function postingsOf(row) {
    return row.postings || [row];
  }

  /* Same company + same normalized title (`group`, from the data) in more than one
     department: one row, the best-scored posting as its face, `postings` holding them all
     (best first). Anything else stays as it is. */
  function groupJobs(jobs) {
    var byGroup = {};
    jobs.forEach(function (j) {
      if (j.group) (byGroup[j.group] = byGroup[j.group] || []).push(j);
    });
    var done = {};
    var rows = [];
    jobs.forEach(function (j) {
      var members = j.group ? byGroup[j.group] : null;
      var depts = {};
      (members || []).forEach(function (m) { depts[m.department || "?"] = true; });
      if (!members || members.length < 2 || Object.keys(depts).length < 2) { rows.push(j); return; }
      if (done[j.group]) return;
      done[j.group] = true;
      var sorted = members.slice().sort(function (a, b) {
        return (b.score === null ? -1 : b.score) - (a.score === null ? -1 : a.score);
      });
      var row = Object.assign({}, sorted[0]);
      row.postings = sorted;
      row.departments = Object.keys(depts).sort();
      rows.push(row);
    });
    return rows;
  }

  /* A row's status: its posting's, or the most advanced one of its group. */
  function rowStatus(row, apps) {
    return postingsOf(row).reduce(function (best, p) {
      var s = statusOf(apps[p.key]);
      return STATUS_RANK[s] > STATUS_RANK[best] ? s : best;
    }, "ignored");
  }

  /* The "Aujourd'hui" view, over rows (`groupJobs`).
     queue: rows still waiting for me (to_review, to_apply), to_apply first, then by score.
     followups: applications whose follow-up date is today or past, oldest first, with their
     posting when the snapshot still lists it. */
  function todayItems(rows, apps, today) {
    var queue = rows.filter(function (r) { return isActive(rowStatus(r, apps)); });
    queue.sort(function (a, b) {
      var sa = rowStatus(a, apps) === "to_apply" ? 0 : 1;
      var sb = rowStatus(b, apps) === "to_apply" ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return (b.score === null ? -1 : b.score) - (a.score === null ? -1 : a.score);
    });
    var byKey = {};
    rows.forEach(function (r) { postingsOf(r).forEach(function (p) { byKey[p.key] = p; }); });
    var followups = Object.keys(apps)
      .filter(function (k) { return isDue(apps[k], today); })
      .map(function (k) {
        return { key: k, app: apps[k], job: byKey[k] || null, late: daysBetween(apps[k].follow_up_at, today) };
      })
      .sort(function (a, b) {
        return a.app.follow_up_at < b.app.follow_up_at ? -1 : a.app.follow_up_at > b.app.follow_up_at ? 1 : 0;
      });
    return { queue: queue, followups: followups };
  }

  /* Things waiting for me today, each counted once: a queued row with a follow-up due is one
     thing, not two. */
  function todayCount(items) {
    var inQueue = {};
    items.queue.forEach(function (r) { postingsOf(r).forEach(function (p) { inQueue[p.key] = true; }); });
    return items.queue.length + items.followups.filter(function (f) { return !inQueue[f.key]; }).length;
  }

  function isHttpsUrl(value) {
    if (typeof value !== "string" || value.length > URL_MAX) return false;
    var u;
    try { u = new URL(value); } catch (e) { return false; }
    return u.protocol === "https:" && !!u.hostname && !u.username && !u.password;
  }

  /* The same rules as the Worker, checked before sending so a typo shows at the field. */
  function validateRecord(rec) {
    var errors = {};
    if (STATUSES.indexOf(rec.status) < 0) errors.status = "Choisis un statut.";
    if (rec.applied_at && !isDay(rec.applied_at)) errors.applied_at = "Indique une vraie date.";
    if (rec.follow_up_at && !isDay(rec.follow_up_at)) errors.follow_up_at = "Indique une vraie date.";
    if (rec.note && rec.note.length > NOTE_MAX) errors.note = NOTE_MAX + " caractères au maximum.";
    if (rec.cv_url && !isHttpsUrl(rec.cv_url)) errors.cv_url = "Doit être un lien https://.";
    return errors;
  }

  function blank(rec) {
    return {
      status: statusOf(rec),
      applied_at: (rec && rec.applied_at) || "",
      follow_up_at: (rec && rec.follow_up_at) || "",
      note: (rec && rec.note) || "",
      cv_url: (rec && rec.cv_url) || ""
    };
  }

  /* fetch wrapper for /api/. Same origin only, JSON only; errors carry the API's message. */
  function client(fetchImpl) {
    function call(method, path, body) {
      var init = { method: method, headers: { Accept: "application/json" }, credentials: "same-origin" };
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      return fetchImpl("/api/" + path, init).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (payload) {
          if (!res.ok) {
            var err = new Error(payload && typeof payload.error === "string" ? payload.error : "HTTP " + res.status);
            err.status = res.status;
            throw err;
          }
          return payload;
        });
      });
    }
    return {
      list: function () { return call("GET", "applications"); },
      save: function (key, rec) { return call("PUT", "applications/" + encodeURIComponent(key), rec); },
      decide: function (key, label, score) {
        return call("POST", "decisions", { job_key: key, label: label, score_at_decision: score });
      },
      /* Undo of a verdict given in the triage view. */
      undecide: function (id) { return call("DELETE", "decisions/" + encodeURIComponent(String(id))); },
      /* "je maîtrise" (on) or its undo (off). The name is a vocabulary term. */
      overrideSkill: function (skill, on) {
        return call(on ? "PUT" : "DELETE", "skill-overrides/" + encodeURIComponent(skill));
      }
    };
  }

  var api = {
    STATUSES: STATUSES,
    STATUS_TEXT: STATUS_TEXT,
    LABELS: LABELS,
    LABEL_TEXT: LABEL_TEXT,
    NOTE_MAX: NOTE_MAX,
    statusOf: statusOf,
    isActive: isActive,
    isDay: isDay,
    localDay: localDay,
    daysBetween: daysBetween,
    isDue: isDue,
    todayItems: todayItems,
    todayCount: todayCount,
    groupJobs: groupJobs,
    rowStatus: rowStatus,
    postingsOf: postingsOf,
    STATUS_RANK: STATUS_RANK,
    isHttpsUrl: isHttpsUrl,
    validateRecord: validateRecord,
    blank: blank,
    client: client
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMTracking = api;
})(this);
