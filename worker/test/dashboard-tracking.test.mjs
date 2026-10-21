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

describe("Aujourd'hui count", () => {
  test("a queued job with a follow-up due counts once", () => {
    const items = T.todayItems(JOBS, APPS, TODAY);
    // queue: apply, review, new; follow-ups: applied, gone, apply (already queued)
    assert.equal(items.queue.length + items.followups.length, 6);
    assert.equal(T.todayCount(items), 5);
  });

  test("a group counts once and is queued while its best status is active", () => {
    const rows = T.groupJobs([
      job("ft:a", 80, { group: "acme|ingenieur devops", department: "75" }),
      job("ft:b", 90, { group: "acme|ingenieur devops", department: "69" }),
      job("ft:c", 70, { group: "acme|ingenieur devops", department: "31" }),
    ]);
    assert.equal(rows.length, 1);
    assert.equal(T.todayCount(T.todayItems(rows, {}, TODAY)), 1);
    const applied = { "ft:c": { status: "applied" } };
    assert.equal(T.todayItems(rows, applied, TODAY).queue.length, 0);
  });
});

describe("grouping", () => {
  const g = (key, score, department, extra = {}) =>
    job(key, score, { group: "acme|ingenieur devops", department, ...extra });

  test("one posting in three departments is one row led by the best score", () => {
    const rows = T.groupJobs([g("ft:a", 80, "75"), job("ft:x", 50), g("ft:b", 90, "69"), g("ft:c", 70, "31")]);
    assert.equal(rows.length, 2);
    const row = rows.find((r) => r.postings);
    assert.equal(row.key, "ft:b");
    assert.deepEqual(row.postings.map((p) => p.key), ["ft:b", "ft:a", "ft:c"]);
    assert.deepEqual(row.departments, ["31", "69", "75"]);
  });

  test("the same department twice, a single posting, or no company are never grouped", () => {
    assert.equal(T.groupJobs([g("ft:a", 80, "75"), g("ft:b", 90, "75")]).length, 2);
    assert.equal(T.groupJobs([g("ft:a", 80, "75")])[0].postings, undefined);
    const anon = [job("ft:a", 80, { group: null, department: "75" }), job("ft:b", 90, { group: null, department: "69" })];
    assert.equal(T.groupJobs(anon).length, 2);
  });

  test("the row shows the most advanced status of its postings", () => {
    const [row] = T.groupJobs([g("ft:a", 80, "75"), g("ft:b", 90, "69")]);
    assert.equal(T.rowStatus(row, {}), "to_review");
    assert.equal(T.rowStatus(row, { "ft:a": { status: "ignored" } }), "to_review");
    assert.equal(T.rowStatus(row, { "ft:a": { status: "to_apply" }, "ft:b": { status: "ignored" } }), "to_apply");
    assert.equal(T.rowStatus(row, { "ft:a": { status: "applied" }, "ft:b": { status: "interview" } }), "interview");
    assert.equal(T.rowStatus(row, { "ft:a": { status: "ignored" }, "ft:b": { status: "ignored" } }), "ignored");
  });
});

describe("statuses", () => {
  test("a job with no row, or an unknown status, shows as À examiner", () => {
    assert.equal(T.statusOf(undefined), "to_review");
    assert.equal(T.statusOf({ status: "<img src=x onerror=alert(1)>" }), "to_review");
    assert.equal(T.STATUS_TEXT[T.statusOf({ status: "interview" })], "Entretien");
  });

  test("every status has its text", () => {
    for (const s of T.STATUSES) assert.match(T.STATUS_TEXT[s], /^[A-ZÀ-Ý]/);
    for (const l of T.LABELS) assert.match(T.LABEL_TEXT[l], /^[A-ZÀ-Ý]/);
    assert.equal(T.STATUS_TEXT.to_apply, "À candidater");
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

describe("Offres search", () => {
  const row = { title: "Ingénieur plateforme Kubernetes", company: "Orbital Data", location: "Nantes 44" };
  const find = (q, r = row) => T.matchesWords(r, T.queryWords(q));

  test("words are folded: case and accents never matter", () => {
    assert.equal(T.fold("Ingénieur Élève ÇA"), "ingenieur eleve ca");
    assert.deepEqual(T.queryWords("  Orbital   KUBERNETES "), ["orbital", "kubernetes"]);
    assert.deepEqual(T.queryWords(""), []);
  });

  test("every word must match, in any order, across title, company and location", () => {
    assert.ok(find("orbital kubernetes"));
    assert.ok(find("kubernetes orbital"));
    assert.ok(find("ingenieur"));
    assert.ok(find("INGÉNIEUR nantes"));
    assert.ok(find("plateforme kube"));
    assert.ok(!find("orbital azure"));
    assert.ok(find("")); // no words: everything
  });

  test("a group matches on any of its postings' locations", () => {
    const grouped = T.groupJobs([
      { key: "ft:a", id: "ft:a", score: 80, title: "DevOps", company: "Nordwind", location: "Paris 75", group: "nordwind|devops", department: "75" },
      { key: "ft:b", id: "ft:b", score: 70, title: "DevOps", company: "Nordwind", location: "Lyon 69", group: "nordwind|devops", department: "69" },
    ]);
    assert.equal(grouped.length, 1);
    assert.ok(find("nordwind lyon", grouped[0]));
    assert.ok(find("paris devops", grouped[0]));
    assert.ok(!find("nordwind lille", grouped[0]));
  });
});
