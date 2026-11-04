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
  /* The documents' statuses (worker/migrations/0005_documents.sql) and their badge text. */
  var DOC_STATUSES = ["pending", "running", "ready", "failed"];
  var DOC_TEXT = { pending: "En attente", running: "En cours", ready: "Prêt", failed: "Échec" };
  /* Recruiter replies (ADR 0018, worker/migrations/0007_inbox.sql): the kinds Haiku answers
     with, and their text. A sure entretien/refus is applied by the Worker; the rest waits here. */
  var INBOX_KINDS = ["entretien", "refus", "accuse_reception", "relance_recruteur", "autre"];
  var INBOX_KIND_TEXT = {
    entretien: "Entretien",
    refus: "Refus",
    accuse_reception: "Accusé de réception",
    relance_recruteur: "Relance du recruteur",
    autre: "Autre"
  };
  var INBOX_STATE_TEXT = { applied: "Appliquée", to_confirm: "À confirmer", corrected: "Corrigée", ignored: "Ignorée" };
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

  /* Search text: lowercase, accents removed ("Ingénieur" and "ingenieur" are the same word). */
  function fold(s) {
    return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function queryWords(q) {
    return fold(q).split(/\s+/).filter(Boolean);
  }

  /* Every word of the query, in any order, somewhere in the title, the company or a
     location (each posting's, for a group). No words: everything matches. */
  function matchesWords(row, words) {
    if (!words || !words.length) return true;
    var hay = fold([row.title, row.company].concat(postingsOf(row).map(function (p) { return p.location; })).join(" "));
    return words.every(function (w) { return hay.indexOf(w) >= 0; });
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
    if (rec.interview_at && !isDay(rec.interview_at)) errors.interview_at = "Indique une vraie date.";
    if (rec.note && rec.note.length > NOTE_MAX) errors.note = NOTE_MAX + " caractères au maximum.";
    if (rec.cv_url && !isHttpsUrl(rec.cv_url)) errors.cv_url = "Doit être un lien https://.";
    return errors;
  }

  function blank(rec) {
    return {
      status: statusOf(rec),
      applied_at: (rec && rec.applied_at) || "",
      follow_up_at: (rec && rec.follow_up_at) || "",
      interview_at: (rec && rec.interview_at) || "",
      note: (rec && rec.note) || "",
      cv_url: (rec && rec.cv_url) || ""
    };
  }

  /* "Prêt (v2)", "Échec (invented_skill)", "Aucun" when the offer has no documents row. */
  function docText(doc) {
    if (!doc || DOC_STATUSES.indexOf(doc.status) < 0) return "Aucun";
    var text = DOC_TEXT[doc.status];
    if (doc.status === "failed" && doc.error_code) return text + " (" + doc.error_code + ")";
    return doc.version ? text + " (v" + doc.version + ")" : text;
  }

  /* The badge of the latest version: {text, kind, title}; kind is the status or "none". The
     table keeps it short: « Échec » with the code as the tooltip, « — » without a row. */
  function docBadge(doc) {
    if (!doc || DOC_STATUSES.indexOf(doc.status) < 0) return { text: "—", kind: "none", title: "Aucun document" };
    if (doc.status === "failed") return { text: "Échec", kind: "failed", title: doc.error_code || "" };
    if (doc.status === "pending" || doc.status === "running") return { text: "En cours…", kind: doc.status, title: docText(doc) };
    return { text: docText(doc), kind: doc.status, title: "" };
  }

  /* The keys whose latest version is still being made: what the table keeps watching. */
  function inProgress(documents, keys) {
    return (keys || []).filter(function (k) {
      var d = documents && documents[k];
      return d && (d.status === "pending" || d.status === "running");
    });
  }

  /* The kept applications without any documents row: what « Générer les manquants » asks for.
     The Worker applies the same rule (KEEP_STATUSES, no row at all). */
  var KEEP_STATUSES = ["to_apply", "applied", "interview"];
  function missingDocuments(apps, documents) {
    return Object.keys(apps || {}).filter(function (k) {
      return KEEP_STATUSES.indexOf(statusOf(apps[k])) >= 0 && !(documents && documents[k]);
    }).sort();
  }

  /* « 7 documents · ≈ 0,42 $ (reste 58,10 $ ce mois) », from the Worker's documents_budget. */
  function fmtUsd(n) { return n.toFixed(2).replace(".", ",") + " $"; }
  function budgetSummary(budget, count) {
    var ok = budget && typeof budget.remaining_usd === "number" && typeof budget.estimate_usd === "number" && budget.estimate_usd > 0;
    if (!ok) return { affordable: count, estimate_usd: null, text: count + (count > 1 ? " documents" : " document") + " · coût inconnu" };
    var affordable = Math.min(count, Math.floor(budget.remaining_usd / budget.estimate_usd));
    if (affordable <= 0) return { affordable: 0, estimate_usd: 0, text: "Budget mensuel épuisé (reste " + fmtUsd(budget.remaining_usd) + ")" };
    var estimate = Math.round(affordable * budget.estimate_usd * 100) / 100;
    var text = affordable + (affordable > 1 ? " documents" : " document") + " · ≈ " + fmtUsd(estimate) + " (reste " + fmtUsd(budget.remaining_usd) + " ce mois)";
    if (affordable < count) text += " · " + (count - affordable) + " au-delà du budget";
    return { affordable: affordable, estimate_usd: estimate, text: text };
  }

  /* A ready version is downloadable (ADR 0019): the page fetches its content.json (the
     text, the master and the contact sheet) and renders the PDF or the DOCX itself. */
  function documentLinks(key, doc) {
    if (!doc || doc.status !== "ready" || !doc.version) return null;
    return { content: "/api/documents/" + encodeURIComponent(key) + "/v" + doc.version + "/content.json", version: doc.version };
  }

  /* ---- recruiter replies (ADR 0018) ---- */

  function inboxKindText(kind) {
    return INBOX_KIND_TEXT[kind] || "Non classée";
  }

  /* "92 %" from the model's 0–1 confidence; "" when the model did not answer. */
  function confidenceText(c) {
    return typeof c === "number" && c >= 0 && c <= 1 ? Math.round(c * 100) + " %" : "";
  }

  /* What a parked reply points at: the proposed application's offer (title · company), or
     "Candidature inconnue" when the model found none or the offer left the page. */
  function inboxSummary(item, postings) {
    var key = item && item.proposed_key;
    var j = key && postings ? postings[key] : null;
    if (!key) return { key: null, text: "Candidature inconnue" };
    if (!j) return { key: key, text: key };
    return { key: key, text: [j.title || key, j.company || null].filter(Boolean).join(" · ") };
  }

  /* The replies that touched one application (confirmed, corrected or proposed), newest first. */
  function inboxHistoryFor(key, history) {
    return (history || []).filter(function (it) {
      return it && (it.applied_key === key || (it.state === "to_confirm" && it.proposed_key === key));
    }).sort(function (a, b) { return String(b.received_at || "").localeCompare(String(a.received_at || "")); });
  }

  /* The applications a reply can be attached to: the sent ones first, then the rest. */
  function inboxTargets(apps, postings) {
    return Object.keys(apps || {}).filter(function (k) {
      var st = statusOf(apps[k]);
      return st !== "ignored" && st !== "to_review";
    }).sort(function (a, b) {
      var sa = statusOf(apps[a]) === "applied" ? 0 : 1, sb = statusOf(apps[b]) === "applied" ? 0 : 1;
      if (sa !== sb) return sa - sb;
      var ta = postings && postings[a] ? (postings[a].title || "") : a, tb = postings && postings[b] ? (postings[b].title || "") : b;
      return ta.localeCompare(tb);
    });
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
      },
      /* The generated CV + letter versions of an offer, and a new version on demand (ADR 0017). */
      documents: function (key) { return call("GET", "documents/" + encodeURIComponent(key)); },
      regenerate: function (key) { return call("POST", "documents/" + encodeURIComponent(key) + "/regenerate"); },
      /* What the browser renders a version from: {content, master, contact} (ADR 0019). */
      content: function (key, version) { return call("GET", "documents/" + encodeURIComponent(key) + "/v" + version + "/content.json"); },
      /* A same-origin file as bytes (the PDF fonts). */
      bytes: function (url) {
        return fetchImpl(url, { credentials: "same-origin" }).then(function (res) {
          if (!res.ok) { var err = new Error("HTTP " + res.status); err.status = res.status; throw err; }
          return res.arrayBuffer();
        }).then(function (buf) { return new Uint8Array(buf); });
      },
      /* « Générer les manquants »: a pending row per kept offer without one, within the budget. */
      requestMissing: function () { return call("POST", "documents/missing"); },
      /* « Lancer maintenant » in Exécutions: the Worker answers 202 and runs the pass after. */
      runAi: function () { return call("POST", "ai/run"); },
      runDocuments: function () { return call("POST", "documents/run"); },
      /* Valider / Corriger / Ignorer a recruiter reply (ADR 0018). */
      inboxAct: function (id, body) { return call("PUT", "inbox/" + encodeURIComponent(id), body); }
    };
  }

  var api = {
    STATUSES: STATUSES,
    STATUS_TEXT: STATUS_TEXT,
    LABELS: LABELS,
    LABEL_TEXT: LABEL_TEXT,
    NOTE_MAX: NOTE_MAX,
    DOC_STATUSES: DOC_STATUSES,
    DOC_TEXT: DOC_TEXT,
    INBOX_KINDS: INBOX_KINDS,
    INBOX_KIND_TEXT: INBOX_KIND_TEXT,
    INBOX_STATE_TEXT: INBOX_STATE_TEXT,
    inboxKindText: inboxKindText,
    confidenceText: confidenceText,
    inboxSummary: inboxSummary,
    inboxHistoryFor: inboxHistoryFor,
    inboxTargets: inboxTargets,
    docText: docText,
    docBadge: docBadge,
    missingDocuments: missingDocuments,
    inProgress: inProgress,
    budgetSummary: budgetSummary,
    documentLinks: documentLinks,
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
    fold: fold,
    queryWords: queryWords,
    matchesWords: matchesWords,
    STATUS_RANK: STATUS_RANK,
    isHttpsUrl: isHttpsUrl,
    validateRecord: validateRecord,
    blank: blank,
    client: client
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMTracking = api;
})(this);
