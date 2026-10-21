/* job-match application tracking: the logic the dashboard shares with its tests. No DOM
   here. The statuses and labels match the D1 schema (worker/migrations/0001_tracking.sql),
   the Worker and src/job_match/tracking/constants.py; a test checks they agree. */
(function (root) {
  "use strict";

  var STATUSES = ["to_review", "to_apply", "applied", "interview", "rejected", "ignored"];
  var STATUS_TEXT = {
    to_review: "To review",
    to_apply: "To apply",
    applied: "Applied",
    interview: "Interview",
    rejected: "Rejected",
    ignored: "Ignored"
  };
  var LABELS = ["good_fit", "off_topic", "too_senior", "missing_skill"];
  var LABEL_TEXT = {
    good_fit: "Good fit",
    off_topic: "Off topic",
    too_senior: "Too senior",
    missing_skill: "Missing skill"
  };
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

  /* The "Aujourd'hui" view.
     queue: jobs still waiting for me (no row, to_review, to_apply), to_apply first, then by
     score. followups: applications whose follow-up date is today or past, oldest first, with
     their job when the snapshot still lists it. */
  function todayItems(jobs, apps, today) {
    var queue = jobs.filter(function (j) { return isActive(statusOf(apps[j.key])); });
    queue.sort(function (a, b) {
      var sa = statusOf(apps[a.key]) === "to_apply" ? 0 : 1;
      var sb = statusOf(apps[b.key]) === "to_apply" ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return (b.score === null ? -1 : b.score) - (a.score === null ? -1 : a.score);
    });
    var byKey = {};
    jobs.forEach(function (j) { byKey[j.key] = j; });
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

  function isHttpsUrl(value) {
    if (typeof value !== "string" || value.length > URL_MAX) return false;
    var u;
    try { u = new URL(value); } catch (e) { return false; }
    return u.protocol === "https:" && !!u.hostname && !u.username && !u.password;
  }

  /* The same rules as the Worker, checked before sending so a typo shows at the field. */
  function validateRecord(rec) {
    var errors = {};
    if (STATUSES.indexOf(rec.status) < 0) errors.status = "Pick a status.";
    if (rec.applied_at && !isDay(rec.applied_at)) errors.applied_at = "Use a real date.";
    if (rec.follow_up_at && !isDay(rec.follow_up_at)) errors.follow_up_at = "Use a real date.";
    if (rec.note && rec.note.length > NOTE_MAX) errors.note = "At most " + NOTE_MAX + " characters.";
    if (rec.cv_url && !isHttpsUrl(rec.cv_url)) errors.cv_url = "Must be an https:// link.";
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
    isHttpsUrl: isHttpsUrl,
    validateRecord: validateRecord,
    blank: blank,
    client: client
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMTracking = api;
})(this);
