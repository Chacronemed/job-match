// The auto-archive rule (ADR 0028): worker/src/archive.js and the page's copy in
// tracking.js must give the same answer on every case, and the constants must agree.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { describe, test } from "node:test";

import { ARCHIVE, archiveReason, archiveState, dayOf, decisionIndex, KEPT_DAYS, PUBLISHED_DAYS } from "../src/archive.js";

const require = createRequire(import.meta.url);
const T = require("../../src/job_match/dashboard/assets/tracking.js");

const TODAY = "2026-11-06";
const ago = (days) => new Date(Date.parse(TODAY + "T09:00:00Z") - days * 86400000).toISOString();
const app = (over = {}) => ({ status: "to_apply", updated_at: ago(1), reactivated_at: null, ...over });
const kept = (days) => ({ label: "good_fit", created_at: ago(days) });

const CASES = [
  ["kept 16 days ago", app(), null, kept(16), { reason: "kept", days: 16 }],
  ["kept 15 days ago", app(), null, kept(15), null],
  ["kept 14 days ago", app(), null, kept(14), null],
  ["published 21 days ago, kept yesterday", app(), { published_at: ago(21) }, kept(1), { reason: "published", days: 21 }],
  ["published 20 days ago, kept yesterday", app(), { published_at: ago(20) }, kept(1), null],
  ["publication unknown, kept 10 days ago", app(), { published_at: null }, kept(10), null],
  ["no decision at all: no kept day", app({ updated_at: ago(40) }), null, null, null],
  ["a drop decision is not a keep", app(), null, { label: "off_topic", created_at: ago(40) }, null],
  ["applied, kept 60 days ago", app({ status: "applied" }), { published_at: ago(60) }, kept(60), null],
  ["interview", app({ status: "interview" }), null, kept(60), null],
  ["rejected", app({ status: "rejected" }), null, kept(60), null],
  ["reactivated 3 days ago: counter restarted, published rule off", app({ reactivated_at: ago(3) }), { published_at: ago(40) }, kept(30), null],
  ["reactivated 16 days ago", app({ reactivated_at: ago(16) }), { published_at: ago(40) }, kept(30), { reason: "kept", days: 16 }],
  ["expired wins", app(), { closed: true, published_at: ago(40) }, kept(30), null],
  ["both rules: the kept one is reported", app(), { published_at: ago(40) }, kept(30), { reason: "kept", days: 30 }],
  ["no row", undefined, null, kept(30), null],
];

describe("archive rule", () => {
  for (const [name, a, posting, decision, expected] of CASES) {
    test(name, () => {
      assert.deepEqual(archiveState(a, posting, decision, TODAY), expected);
      assert.deepEqual(T.archiveState(a, posting, decision, TODAY), expected, "tracking.js agrees");
      assert.equal(T.isArchived(a, posting, decision, TODAY), expected !== null);
    });
  }

  test("the constants agree between the Worker and the page", () => {
    assert.deepEqual(T.ARCHIVE, ARCHIVE);
    assert.deepEqual(ARCHIVE, { kept_days: KEPT_DAYS, published_days: PUBLISHED_DAYS });
    // a custom config is honoured by both copies
    const cfg = { kept_days: 10, published_days: 12 };
    assert.deepEqual(archiveState(app(), null, kept(11), TODAY, cfg), { reason: "kept", days: 11 });
    assert.deepEqual(T.archiveState(app(), null, kept(11), TODAY, cfg), { reason: "kept", days: 11 });
  });

  test("the reason reads as the page says it", () => {
    assert.equal(archiveReason({ reason: "kept", days: 17 }), "gardée il y a 17 jours");
    assert.equal(archiveReason({ reason: "published", days: 23 }), "publiée il y a 23 jours");
    assert.equal(archiveReason({ reason: "kept", days: 1 }), "gardée il y a 1 jour");
    assert.equal(T.archiveReason({ reason: "published", days: 23 }), "publiée il y a 23 jours");
    assert.equal(archiveReason(null), "");
  });

  test("days are read from any ISO value", () => {
    assert.equal(dayOf("2026-11-06T09:00:00.000Z"), "2026-11-06");
    assert.equal(dayOf("2026-11-06"), "2026-11-06");
    assert.equal(dayOf("2026-02-30T00:00:00Z"), null);
    assert.equal(dayOf(null), null);
    assert.equal(T.keptDay(app({ reactivated_at: "2026-11-01T10:00:00Z" }), kept(30)), "2026-11-01");
    assert.equal(T.keptDay(app(), kept(30)), ago(30).slice(0, 10));
    assert.equal(T.keptDay(app(), null), null);
  });

  test("decisionIndex keeps the latest decision per key as the Worker reads it", () => {
    const idx = decisionIndex([{ job_key: "a", label: "good_fit", created_at: "2026-10-01T00:00:00Z" }, null, { label: "x" }]);
    assert.deepEqual(idx.get("a"), { label: "good_fit", created_at: "2026-10-01T00:00:00Z" });
    assert.equal(idx.size, 1);
  });
});
