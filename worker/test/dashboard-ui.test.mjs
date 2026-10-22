// The dashboard's pure UI logic: the score « Relevé » (score.js) and the palette's matching
// (palette.js). The DOM parts are checked in the browser (docs/design/AUDIT.md). French
// spacing: a no-break space (U+00A0) inside « » and before « : ».
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { describe, test } from "node:test";

const require = createRequire(import.meta.url);
const S = require("../../src/job_match/dashboard/assets/score.js");
const Pal = require("../../src/job_match/dashboard/assets/palette.js");

const T = { strong: 75, min_score: 50 };
const job = (score, explanations, extra = {}) => ({ score, explanations, section: "eligible", ...extra });

describe("breakdown", () => {
  test("reads every weight from the scorer's lines and finds the start", () => {
    const b = S.breakdown(job(64, [
      "Matched preferred: docker (+3)", "Missed preferred: aws", "Matched preferred: kubernetes (+4)",
      "Matched negative: sap (-5)", "Title keyword match: devops (+10)",
    ]));
    assert.deepEqual(b.lines, [
      { kind: "up", label: "docker", value: 3 },
      { kind: "up", label: "kubernetes", value: 4 },
      { kind: "down", label: "sap", value: -5 },
      { kind: "up", label: "titre « devops »", value: 10 },
    ]);
    assert.equal(b.start, 52);
    assert.equal(b.total, 64);
    assert.equal(b.capped, false);
  });

  test("a capped score has no start line: the sum before the cap is not in the data", () => {
    const b = S.breakdown(job(100, ["Matched preferred: kubernetes (+40)", "Title keyword match: sre (+20)"]));
    assert.equal(b.capped, true);
    assert.equal(b.start, null);
    assert.equal(S.breakdown(job(0, ["Matched negative: cobol (-60)"])).start, null);
  });

  test("no score, no ledger; no factor, the start is the score", () => {
    assert.equal(S.breakdown(job(null, [])), null);
    assert.equal(S.breakdown({}), null);
    const b = S.breakdown(job(50, ["Missed preferred: aws", "stretch: requires 3y, you have 2"]));
    assert.deepEqual(b.lines, []);
    assert.equal(b.start, 50);
  });
});

describe("band and gap sentence", () => {
  test("the band is the pipeline's section, in words", () => {
    assert.equal(S.band({ section: "strong" }).label, "Forte");
    assert.equal(S.band({ section: "eligible" }).label, "Éligible");
    assert.equal(S.band({ section: "stretch" }).label, "À tenter");
    assert.equal(S.band({}).key, "low");
  });

  test("says how many points are missing for « forte », singular and plural", () => {
    assert.equal(S.gapSentence(job(64, []), T), "Il manque 11 points pour forte.");
    assert.equal(S.gapSentence(job(74, []), T), "Il manque 1 point pour forte.");
    assert.equal(S.gapSentence(job(75, [], { section: "strong" }), T), "Forte, pile au seuil (75).");
    assert.equal(S.gapSentence(job(82, [], { section: "strong" }), T), "Forte : 7 points au-dessus du seuil.");
  });

  test("a stretch offer names the years from its own explanation", () => {
    const j = job(49, ["stretch: requires 3y, you have 2"], { section: "stretch" });
    assert.equal(S.gapSentence(j, T), "À tenter : 3 ans requis, tu en as 2.");
    assert.equal(S.gapSentence(job(49, [], { section: "stretch" }), T), "À tenter : un peu plus d’expérience que ton profil.");
  });

  test("signed weights use a real minus sign", () => {
    assert.equal(S.signed(3), "+3");
    assert.equal(S.signed(-5), "−5");
    assert.equal(S.signed(0), "0");
  });
});

describe("palette match", () => {
  test("every word must appear, in any order, accents and case folded", () => {
    assert.deepEqual(Pal.match("orbital kube", "Ingénieur plateforme Kubernetes Orbital Data Nantes"), [[21, 25], [32, 39]]);
    assert.deepEqual(Pal.match("ingenieur", "Ingénieur DevOps"), [[0, 9]]);
    assert.equal(Pal.match("orbital lyon", "Orbital Data Nantes"), null);
    assert.deepEqual(Pal.match("  ", "anything"), []);
  });
});
