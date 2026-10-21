// The dashboard's tracking logic (src/job_match/dashboard/assets/tracking.js): what the
// "Aujourd'hui" view shows, how statuses render, what the form refuses before sending.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { describe, test } from "node:test";

const require = createRequire(import.meta.url);
const T = require("../../src/job_match/dashboard/assets/tracking.js");

const TODAY = "2026-10-20";
const job = (key, score, extra = {}) => ({ key, id: key, score, title: key, ...extra });
const JOBS = [
  job("ft:new", 60),
  job("ft:review", 90),
  job("ft:apply", 50),
  job("ft:applied", 95),
  job("ft:interview", 80),
  job("ft:rejected", 70),
  job("ft:ignored", 99),
];
const APPS = {
  "ft:review": { status: "to_review" },
  "ft:apply": { status: "to_apply", follow_up_at: "2026-10-20" },
  "ft:applied": { status: "applied", follow_up_at: "2026-10-17" },
  "ft:interview": { status: "interview", follow_up_at: "2026-10-25" },
  "ft:rejected": { status: "rejected", follow_up_at: "2026-10-01" },
  "ft:ignored": { status: "ignored" },
  "ft:gone": { status: "applied", follow_up_at: "2026-10-18" },
};

describe("Aujourd'hui", () => {
  test("queue keeps untracked, to_review and to_apply; to_apply first, then by score", () => {
    const { queue } = T.todayItems(JOBS, APPS, TODAY);
    assert.deepEqual(queue.map((j) => j.key), ["ft:apply", "ft:review", "ft:new"]);
  });

  test("handled statuses never reach the queue", () => {
    const { queue } = T.todayItems(JOBS, APPS, TODAY);
    for (const handled of ["applied", "interview", "rejected", "ignored"]) {
      assert.ok(!queue.some((j) => T.statusOf(APPS[j.key]) === handled), handled);
    }
  });

  test("follow-ups due today or overdue, oldest first, closed applications left out", () => {
    const { followups } = T.todayItems(JOBS, APPS, TODAY);
    assert.deepEqual(followups.map((f) => [f.key, f.late]), [
      ["ft:applied", 3],
      ["ft:gone", 2],
      ["ft:apply", 0],
    ]);
  });

  test("a follow-up whose offer left the snapshot is kept, without a job", () => {
    const gone = T.todayItems(JOBS, APPS, TODAY).followups.find((f) => f.key === "ft:gone");
    assert.equal(gone.job, null);
    assert.equal(T.todayItems(JOBS, APPS, TODAY).followups.find((f) => f.key === "ft:applied").job.key, "ft:applied");
  });

  test("without tracking data every job is in the queue", () => {
    const { queue, followups } = T.todayItems(JOBS, {}, TODAY);
    assert.equal(queue.length, JOBS.length);
    assert.equal(followups.length, 0);
  });
});

describe("statuses", () => {
  test("a job with no row, or an unknown status, shows as To review", () => {
    assert.equal(T.statusOf(undefined), "to_review");
    assert.equal(T.statusOf({ status: "<img src=x onerror=alert(1)>" }), "to_review");
    assert.equal(T.STATUS_TEXT[T.statusOf({ status: "interview" })], "Interview");
  });

  test("every status has its text", () => {
    for (const s of T.STATUSES) assert.match(T.STATUS_TEXT[s], /^[A-Z]/);
    for (const l of T.LABELS) assert.match(T.LABEL_TEXT[l], /^[A-Z]/);
  });

  test("blank fills every field for the form", () => {
    assert.deepEqual(T.blank(undefined), { status: "to_review", applied_at: "", follow_up_at: "", note: "", cv_url: "" });
    assert.equal(T.blank({ status: "applied", note: null }).note, "");
  });
});

describe("form validation (same rules as the Worker)", () => {
  const ok = { status: "applied", applied_at: "2026-10-20", follow_up_at: "", note: "", cv_url: "" };
  test("a valid record has no error", () => {
    assert.deepEqual(T.validateRecord(ok), {});
  });
  const bad = {
    status: { ...ok, status: "hired" },
    applied_at: { ...ok, applied_at: "2026-02-30" },
    follow_up_at: { ...ok, follow_up_at: "tomorrow" },
    note: { ...ok, note: "x".repeat(2001) },
    cv_url: { ...ok, cv_url: "http://example.com/cv" },
  };
  for (const [field, rec] of Object.entries(bad)) {
    test(`${field} is refused`, () => {
      assert.deepEqual(Object.keys(T.validateRecord(rec)), [field]);
    });
  }
  test("only https links, no credentials, no script schemes", () => {
    assert.ok(T.isHttpsUrl("https://drive.example.com/cv.pdf"));
    for (const u of ["javascript:alert(1)", "data:text/html,x", "https://u:p@x.com", "ftp://x.com", "notaurl"]) {
      assert.ok(!T.isHttpsUrl(u), u);
    }
  });
  test("local day and day arithmetic", () => {
    assert.equal(T.localDay(new Date(2026, 0, 5, 23, 30)), "2026-01-05");
    assert.equal(T.daysBetween("2026-10-17", "2026-10-20"), 3);
  });
});

describe("API client", () => {
  function fakeFetch(status, body) {
    const calls = [];
    const fn = async (url, init) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    };
    fn.calls = calls;
    return fn;
  }

  test("PUT goes to /api/applications/<encoded key> as JSON", async () => {
    const f = fakeFetch(200, { application: { job_key: "ft:1" } });
    const res = await T.client(f).save("france_travail:1A", { status: "applied" });
    assert.equal(res.application.job_key, "ft:1");
    assert.equal(f.calls[0].url, "/api/applications/france_travail%3A1A");
    assert.equal(f.calls[0].init.method, "PUT");
    assert.equal(f.calls[0].init.headers["Content-Type"], "application/json");
    assert.equal(f.calls[0].init.credentials, "same-origin");
  });

  test("an API error carries its message and status", async () => {
    const f = fakeFetch(400, { error: "cv_url: must be an https URL" });
    await assert.rejects(T.client(f).save("ft:1", {}), (err) => {
      assert.equal(err.message, "cv_url: must be an https URL");
      assert.equal(err.status, 400);
      return true;
    });
  });

  test("a decision posts the label and the score", async () => {
    const f = fakeFetch(201, { decision: {} });
    await T.client(f).decide("ft:1", "too_senior", 64);
    assert.equal(f.calls[0].url, "/api/decisions");
    assert.deepEqual(JSON.parse(f.calls[0].init.body), { job_key: "ft:1", label: "too_senior", score_at_decision: 64 });
  });

  test("je maîtrise puts the encoded skill, Annuler deletes it, no body", async () => {
    const f = fakeFetch(200, { skill_override: {} });
    await T.client(f).overrideSkill("gitlab ci", true);
    await T.client(f).overrideSkill("c#", false);
    assert.equal(f.calls[0].url, "/api/skill-overrides/gitlab%20ci");
    assert.equal(f.calls[0].init.method, "PUT");
    assert.equal(f.calls[0].init.body, undefined);
    assert.equal(f.calls[1].url, "/api/skill-overrides/c%23");
    assert.equal(f.calls[1].init.method, "DELETE");
  });
});
