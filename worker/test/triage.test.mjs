// The triage view's logic (src/job_match/dashboard/assets/triage.js): which cards come first,
// what a swipe stores, how undo and the retry queue behave.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { describe, test } from "node:test";

const require = createRequire(import.meta.url);
const X = require("../../src/job_match/dashboard/assets/triage.js");

const RUNS = [
  { pipeline: "jobs_reprocess", started_at: "2026-10-21T09:00:00+00:00" },
  { pipeline: "jobs", started_at: "2026-10-21T07:00:00+00:00" },
  { pipeline: "jobs", started_at: "2026-10-20T07:00:00+00:00" },
];
const job = (key, score, collected, extra = {}) => ({ key, id: key, score, collected_at: collected, ...extra });

describe("queue", () => {
  const rows = [
    job("ft:old-high", 95, "2026-10-15T07:05:00+00:00"),
    job("ft:new-low", 60, "2026-10-21T07:10:00+00:00"),
    job("ft:new-high", 90, "2026-10-21T07:10:00+00:00"),
    job("ft:mid", 99, "2026-10-19T07:05:00+00:00"),
    job("ft:applied", 99, "2026-10-21T07:10:00+00:00"),
    job("ft:ignored", 99, "2026-10-21T07:10:00+00:00"),
    job("ft:to-apply", 99, "2026-10-21T07:10:00+00:00"),
  ];
  const apps = {
    "ft:applied": { status: "applied" },
    "ft:ignored": { status: "ignored" },
    "ft:to-apply": { status: "to_apply" },
  };

  test("latest run is the newest jobs run, not a reprocess", () => {
    assert.equal(X.latestRunAt(RUNS), Date.parse("2026-10-21T07:00:00+00:00"));
    assert.equal(X.latestRunAt([]), 0);
  });

  test("only to_review rows; newest run first, then collected desc, then score", () => {
    const q = X.triageQueue(rows, apps, X.latestRunAt(RUNS));
    assert.deepEqual(q.map((i) => i.row.key), ["ft:new-high", "ft:new-low", "ft:mid", "ft:old-high"]);
    assert.deepEqual(q.map((i) => i.isNew), [true, true, false, false]);
  });

  test("below the digest threshold an offer stays out of the queue; an unscored one stays in", () => {
    const scored = [job("ft:hi", 70, "2026-10-21T07:10:00+00:00"), job("ft:lo", 40, "2026-10-21T07:10:00+00:00"),
      job("ft:none", null, "2026-10-21T07:10:00+00:00"), job("ft:edge", 55, "2026-10-21T07:10:00+00:00")];
    assert.deepEqual(X.triageQueue(scored, {}, 0, 55).map((i) => i.row.key).sort(), ["ft:edge", "ft:hi", "ft:none"]);
    assert.equal(X.triageQueue(scored, {}, 0).length, 4);  // no threshold: everything, as before
  });

  test("a group is one card and leaves the queue once any posting is triaged", () => {
    const T = require("../../src/job_match/dashboard/assets/tracking.js");
    const grouped = T.groupJobs([
      job("ft:a", 80, "2026-10-21T07:10:00+00:00", { group: "acme|devops", department: "75" }),
      job("ft:b", 70, "2026-10-21T07:10:00+00:00", { group: "acme|devops", department: "69" }),
    ]);
    assert.equal(X.triageQueue(grouped, {}, 0).length, 1);
    assert.equal(X.triageQueue(grouped, { "ft:b": { status: "ignored" } }, 0).length, 1);
    assert.equal(X.triageQueue(grouped, { "ft:b": { status: "to_apply" } }, 0).length, 0);
  });

  test("batches of 20 with progress inside the batch", () => {
    assert.deepEqual(X.batchOf(0, 45), { index: 0, count: 3, start: 0, size: 20, done: 0 });
    assert.deepEqual(X.batchOf(27, 45), { index: 1, count: 3, start: 20, size: 20, done: 7 });
    assert.deepEqual(X.batchOf(44, 45), { index: 2, count: 3, start: 40, size: 5, done: 4 });
  });
});

describe("swipe", () => {
  test("right keeps (to_apply + good_fit), left drops (ignored, verdict optional)", () => {
    assert.deepEqual(X.SWIPE.right, { status: "to_apply", label: "good_fit" });
    assert.deepEqual(X.SWIPE.left, { status: "ignored", label: null });
    assert.deepEqual(X.REASONS, ["off_topic", "too_senior", "missing_skill", "location"]);
  });

  test("the stored record keeps the other fields of the previous one", () => {
    const prev = { status: "to_review", note: "vu au salon", follow_up_at: "2026-10-30" };
    assert.deepEqual(X.swipeRecord(prev, "right"),
      { status: "to_apply", applied_at: "", follow_up_at: "2026-10-30", note: "vu au salon", cv_url: "" });
    assert.equal(X.swipeRecord(undefined, "left").status, "ignored");
    assert.throws(() => X.swipeRecord(undefined, "up"));
  });

  test("top reasons: the three biggest weights, minus signs included", () => {
    const why = {
      skills: [{ name: "docker", weight: 2 }, { name: "kubernetes", weight: 3 }, { name: "aws", weight: 1 }],
      lowered: [{ name: "sap", weight: -5 }],
    };
    assert.deepEqual(X.topReasons(why).map((r) => r.name), ["sap", "kubernetes", "docker"]);
    assert.deepEqual(X.topReasons(null), []);
  });
});

describe("undo", () => {
  test("last five actions, newest first; a reason chip joins its swipe", () => {
    const u = X.undoStack();
    for (let i = 1; i <= 7; i += 1) u.push({ key: `ft:${i}`, prev: null, decisionIds: [] });
    assert.equal(u.size(), 5);
    assert.equal(u.peek().key, "ft:7");
    assert.ok(u.attach("ft:7", 41));
    assert.ok(!u.attach("ft:1", 42)); // fell off the stack
    assert.deepEqual(u.pop(), { key: "ft:7", prev: null, decisionIds: [41] });
    assert.equal(u.pop().key, "ft:6");
  });
});

describe("retry queue", () => {
  test("network errors wait, in order; a refusal is dropped and reported", async () => {
    let online = false;
    const sent = [];
    const dropped = [];
    const q = X.retryQueue((op) => {
      if (op.payload === "bad") return Promise.reject(Object.assign(new Error("x"), { status: 400 }));
      if (!online) return Promise.reject(new TypeError("Failed to fetch"));
      sent.push(op.payload);
      return Promise.resolve();
    }, (op) => dropped.push(op.payload));
    q.add({ kind: "save", payload: "a" });
    q.add({ kind: "save", payload: "b" });
    assert.equal(await q.flush(), 2);
    assert.equal(q.list()[0].attempts, 1);
    online = true;
    q.add({ kind: "decide", payload: "bad" });
    q.add({ kind: "save", payload: "c" });
    assert.equal(await q.flush(), 0);
    assert.deepEqual(sent, ["a", "b", "c"]);
    assert.deepEqual(dropped, ["bad"]);
  });

  test("the banner counts offers, not calls", () => {
    const save = (key) => ({ kind: "save", payload: { key, rec: { status: "to_apply" } } });
    const decide = (key) => ({ kind: "decide", payload: { key, label: "good_fit" } });
    assert.equal(X.pendingOffers([save("ft:1"), decide("ft:1")]), 1); // one keep = two calls
    assert.equal(X.pendingOffers([save("ft:1"), decide("ft:1"), save("ft:2")]), 2);
    assert.equal(X.pendingOffers([{ kind: "undecide", payload: { id: 7 } }]), 1);
    assert.equal(X.pendingOffers([]), 0);
  });

  test("a 5xx is retried, a 4xx is not", () => {
    assert.ok(X.retryable({ status: 503 }));
    assert.ok(X.retryable(new TypeError("offline")));
    assert.ok(!X.retryable({ status: 409 }));
  });
});

describe("pending actions survive a reload", () => {
  // A Storage-like object; `broken` makes every call throw (private mode, blocked storage).
  function fakeStorage({ broken = false, quota = Infinity } = {}) {
    const data = new Map();
    return {
      data,
      getItem(k) { if (broken) throw new Error("SecurityError"); return data.has(k) ? data.get(k) : null; },
      setItem(k, v) {
        if (broken) throw new Error("SecurityError");
        if (v.length > quota) throw new Error("QuotaExceededError");
        data.set(k, String(v));
      },
      removeItem(k) { if (broken) throw new Error("SecurityError"); data.delete(k); },
    };
  }
  const save = (key, status = "to_apply") => ({ kind: "save", payload: { key, rec: { status } } });
  const offline = () => Promise.reject(new TypeError("Failed to fetch"));

  test("queued actions are written on add and cleared once sent", async () => {
    const store = fakeStorage();
    const q = X.retryQueue(offline, null, X.localStore("jm.pending.v1", store));
    q.add(save("ft:1"));
    q.add({ kind: "decide", payload: { key: "ft:1", label: "good_fit", score: 80 } });
    assert.equal(JSON.parse(store.data.get("jm.pending.v1")).length, 2);
    const sent = [];
    const online = X.retryQueue((op) => { sent.push(op.kind); return Promise.resolve(); }, null,
      X.localStore("jm.pending.v1", store));
    assert.equal(online.size(), 2); // the "reload": a new page reads what the last one left
    assert.equal(await online.flush(), 0);
    assert.deepEqual(sent, ["save", "decide"]);
    assert.equal(store.data.has("jm.pending.v1"), false);
  });

  test("a partial flush keeps the rest, in order, for the next load", async () => {
    const store = fakeStorage();
    const q = X.retryQueue(offline, null, X.localStore("k", store));
    ["ft:a", "ft:b", "ft:c"].forEach((k) => q.add(save(k)));
    let calls = 0;
    const flaky = X.retryQueue(() => (++calls === 1 ? Promise.resolve() : offline()), null, X.localStore("k", store));
    assert.equal(await flaky.flush(), 2);
    const after = X.retryQueue(offline, null, X.localStore("k", store));
    assert.deepEqual(after.list().map((op) => op.payload.key), ["ft:b", "ft:c"]);
  });

  test("malformed or foreign entries are dropped on load", () => {
    const store = fakeStorage();
    store.setItem("k", JSON.stringify([
      save("ft:ok"),
      { kind: "eval", payload: { key: "ft:x" } },
      { kind: "save", payload: { key: "not a key", rec: { status: "to_apply" } } },
      { kind: "save", payload: { key: "ft:y", rec: { status: "hired" } } },
      { kind: "decide", payload: { key: "ft:z", label: "great" } },
      { kind: "undecide", payload: { id: -3 } },
      { kind: "undecide", payload: { id: 7 } },
      null,
      "text",
    ]));
    const q = X.retryQueue(offline, null, X.localStore("k", store));
    assert.deepEqual(q.list().map((op) => op.kind + ":" + (op.payload.key || op.payload.id)), ["save:ft:ok", "undecide:7"]);
    store.setItem("k", "{not json");
    assert.equal(X.retryQueue(offline, null, X.localStore("k", store)).size(), 0);
  });

  test("a store that throws or is full still queues in memory", async () => {
    for (const store of [fakeStorage({ broken: true }), fakeStorage({ quota: 10 })]) {
      const q = X.retryQueue(offline, null, X.localStore("k", store));
      q.add(save("ft:1"));
      assert.equal(q.size(), 1);
      assert.equal(await q.flush(), 1);
    }
    const none = X.localStore("k", null); // no localStorage at all (Node, very old browsers)
    assert.deepEqual(none.load(), []);
    none.save([save("ft:1")]); // must not throw
  });

  test("the queue keeps at most the newest 200 actions", () => {
    const store = fakeStorage();
    const q = X.retryQueue(offline, null, X.localStore("k", store));
    for (let i = 0; i < X.PENDING_MAX + 5; i += 1) q.add(save(`ft:${i}`));
    assert.equal(q.size(), X.PENDING_MAX);
    assert.equal(q.list()[0].payload.key, "ft:5");
    assert.equal(X.retryQueue(offline, null, X.localStore("k", store)).size(), X.PENDING_MAX);
  });
});
