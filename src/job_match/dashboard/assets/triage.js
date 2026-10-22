/* job-match triage ("Tri"): the logic the swipe view shares with its tests. No DOM here.
   Builds on tracking.js (statuses, grouping) and never talks to the network itself: the
   page passes the API calls in, so the queue, undo and retry rules are tested in Node. */
(function (root) {
  "use strict";

  var T = typeof module !== "undefined" && module.exports
    ? require("./tracking.js")
    : root.JMTracking;

  var BATCH = 20;
  var UNDO_MAX = 5;
  /* Reasons offered after a left swipe; each is a verdict label (tracking.LABELS). */
  var REASONS = ["off_topic", "too_senior", "missing_skill", "location"];
  /* What a swipe does: a status, and a verdict when the direction says enough by itself. */
  var SWIPE = {
    right: { status: "to_apply", label: "good_fit" },
    left: { status: "ignored", label: null }
  };

  function time(iso) {
    var t = iso ? Date.parse(iso) : NaN;
    return isNaN(t) ? 0 : t;
  }

  /* When the newest jobs run started: offers collected since then are "Nouveau". */
  function latestRunAt(runs) {
    var best = 0;
    (runs || []).forEach(function (r) {
      if (r && r.pipeline === "jobs") best = Math.max(best, time(r.started_at));
    });
    return best;
  }

  /* Every row still waiting for a first look (to_review), newest run first, then most
     recently collected, then best score. A row is untriaged by definition: no marker.
     `minScore` (the digest threshold, M24): a scored row below it stays in Offres and out of
     the queue; an unscored row is kept, its score is unknown, not low. */
  function triageQueue(rows, apps, runAt, minScore) {
    var floor = typeof minScore === "number" ? minScore : null;
    var queue = rows.filter(function (r) {
      if (floor !== null && typeof r.score === "number" && r.score < floor) return false;
      return T.rowStatus(r, apps) === "to_review";
    })
      .map(function (r) {
        return { row: r, isNew: runAt > 0 && time(r.collected_at) >= runAt, at: time(r.collected_at) };
      });
    queue.sort(function (a, b) {
      if (a.isNew !== b.isNew) return a.isNew ? -1 : 1;
      if (a.at !== b.at) return b.at - a.at;
      return (b.row.score === null ? -1 : b.row.score) - (a.row.score === null ? -1 : a.row.score);
    });
    return queue;
  }

  /* The batch a position falls in: {index, start, size, done}. */
  function batchOf(position, total, size) {
    var n = size || BATCH;
    var index = Math.floor(position / n);
    var start = index * n;
    return { index: index, count: Math.ceil(total / n), start: start,
      size: Math.min(n, total - start), done: position - start };
  }

  /* The three strongest reasons, by how much they moved the score. */
  function topReasons(why, n) {
    var all = [];
    ((why && why.skills) || []).forEach(function (s) { if (typeof s.weight === "number") all.push(s); });
    ((why && why.lowered) || []).forEach(function (s) { if (typeof s.weight === "number") all.push(s); });
    all.sort(function (a, b) { return Math.abs(b.weight) - Math.abs(a.weight); });
    return all.slice(0, n || 3).map(function (s) { return { name: s.name, weight: s.weight }; });
  }

  /* The record a swipe stores: every other field of the previous record is kept. */
  function swipeRecord(prev, direction) {
    var rule = SWIPE[direction];
    if (!rule) throw new Error("unknown direction");
    var rec = T.blank(prev);
    rec.status = rule.status;
    return rec;
  }

  /* The last actions, newest first, at most `max`. */
  function undoStack(max) {
    var items = [];
    var cap = max || UNDO_MAX;
    return {
      push: function (entry) { items.unshift(entry); if (items.length > cap) items.length = cap; },
      pop: function () { return items.shift() || null; },
      peek: function () { return items[0] || null; },
      size: function () { return items.length; },
      /* A verdict posted after the swipe (a reason chip) belongs to the same action. */
      attach: function (key, decisionId) {
        var e = items.filter(function (i) { return i.key === key; })[0];
        if (e) e.decisionIds.push(decisionId);
        return !!e;
      }
    };
  }

  /* Whether a failed call is worth sending again: the network or the server, not a refusal. */
  function retryable(err) {
    return !err || !err.status || err.status >= 500;
  }

  /* How many offers the waiting calls are about: a keep is two calls (status + verdict) for one
     offer. An undone verdict carries no key; it still counts as one when nothing else waits. */
  function pendingOffers(ops) {
    var keys = {};
    (ops || []).forEach(function (op) {
      if (op && op.payload && typeof op.payload.key === "string") keys[op.payload.key] = true;
    });
    var n = Object.keys(keys).length;
    return n || ((ops || []).length ? 1 : 0);
  }

  var PENDING_MAX = 200;
  var JOB_KEY = /^[a-z0-9_]{1,32}:[A-Za-z0-9._-]{1,64}$/;
  var KINDS = { save: true, decide: true, undecide: true };

  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

  /* Only what this page itself would have queued survives a reload: anything else in the
     store (an old format, a hand edit) is left out rather than sent to the API. */
  function validOp(op) {
    if (!isObject(op) || !KINDS[op.kind] || !isObject(op.payload)) return false;
    var p = op.payload;
    if (op.kind === "undecide") return typeof p.id === "number" && p.id > 0 && p.id % 1 === 0;
    if (typeof p.key !== "string" || !JOB_KEY.test(p.key)) return false;
    if (op.kind === "save") return isObject(p.rec) && T.STATUSES.indexOf(p.rec.status) >= 0;
    return T.LABELS.indexOf(p.label) >= 0;
  }

  /* A localStorage slot that never throws: no storage, a private window, bad JSON or a full
     quota all fall back to the queue in memory. */
  function localStore(key, store) {
    function area() {
      try { return store || (typeof localStorage !== "undefined" ? localStorage : null); } catch (e) { return null; }
    }
    return {
      load: function () {
        try {
          var s = area();
          var raw = s ? s.getItem(key) : null;
          var ops = raw ? JSON.parse(raw) : [];
          return Array.isArray(ops) ? ops : [];
        } catch (e) { return []; }
      },
      save: function (ops) {
        try {
          var s = area();
          if (!s) return;
          if (ops.length) s.setItem(key, JSON.stringify(ops)); else s.removeItem(key);
        } catch (e) { /* quota or blocked storage: memory only */ }
      }
    };
  }

  /* Operations that could not reach the API, sent again in order. `send(op)` returns a
     promise; a refused operation (4xx) is dropped and reported through `onDrop`. With a
     `storage` adapter ({load, save}) the queue survives a reload. */
  function retryQueue(send, onDrop, storage) {
    var ops = (storage ? storage.load() : []).filter(validOp).slice(-PENDING_MAX)
      .map(function (op) { return { kind: op.kind, payload: op.payload, attempts: op.attempts | 0 }; });
    var running = false;
    function persist() { if (storage) storage.save(ops); }
    function flush() {
      if (running || !ops.length) return Promise.resolve(ops.length);
      running = true;
      function next() {
        if (!ops.length) { running = false; persist(); return Promise.resolve(0); }
        var op = ops[0];
        op.attempts += 1;
        return send(op).then(function () { ops.shift(); persist(); return next(); }, function (err) {
          if (!retryable(err)) { ops.shift(); persist(); if (onDrop) onDrop(op, err); return next(); }
          running = false;
          persist();
          return ops.length;
        });
      }
      return next();
    }
    return {
      add: function (op) {
        ops.push({ kind: op.kind, payload: op.payload, attempts: 0 });
        if (ops.length > PENDING_MAX) ops.shift();
        persist();
      },
      flush: flush,
      size: function () { return ops.length; },
      list: function () { return ops.slice(); }
    };
  }

  var api = {
    BATCH: BATCH,
    UNDO_MAX: UNDO_MAX,
    REASONS: REASONS,
    SWIPE: SWIPE,
    latestRunAt: latestRunAt,
    triageQueue: triageQueue,
    batchOf: batchOf,
    topReasons: topReasons,
    swipeRecord: swipeRecord,
    undoStack: undoStack,
    retryable: retryable,
    retryQueue: retryQueue,
    localStore: localStore,
    validOp: validOp,
    pendingOffers: pendingOffers,
    PENDING_MAX: PENDING_MAX
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JMTriage = api;
})(this);
