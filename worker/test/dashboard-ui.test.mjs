// The dashboard's pure UI logic: the score « Relevé » (score.js) and the palette's matching
// (palette.js). The DOM parts are checked in the browser (docs/design/AUDIT.md). French
// spacing: a no-break space (U+00A0) inside « » and before « : ».
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { describe, test } from "node:test";

const require = createRequire(import.meta.url);
const S = require("../../src/job_match/dashboard/assets/score.js");
const Pal = require("../../src/job_match/dashboard/assets/palette.js");
const D = require("../../src/job_match/dashboard/assets/description.js");

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
    assert.deepEqual(S.aiBand("fort"), { key: "fort", label: "Fort" });
    assert.equal(S.aiBand("hors_sujet").label, "Hors sujet");
    assert.equal(S.aiBand("maybe"), null);
  });

  test("aiRunLine: a stopped pass names its HTTP status only, counters become stats", () => {
    const stopped = S.aiRunLine({ outcome: "stopped", http_status: 404, counters: { scored: 0, cached: 5, fallback: 0 } });
    assert.deepEqual([stopped.key, stopped.label, stopped.bad], ["stopped", "Arrêté · HTTP 404", true]);
    assert.deepEqual(stopped.stats, [{ label: "jugées", value: 0 }, { label: "en cache", value: 5 }]);
    const ok = S.aiRunLine({ outcome: "ok", http_status: null, counters: { scored: 12, invalid: 1 } });
    assert.deepEqual([ok.label, ok.bad], ["OK", false]);
    assert.deepEqual(ok.stats.map((s) => s.label), ["jugées", "invalides"]);
    assert.equal(S.aiRunLine({ outcome: "failed" }).label, "Échec");
    assert.equal(S.aiRunLine({ outcome: "weird" }).bad, true);
    assert.equal(S.aiRunLine(null).key, "unknown");
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

describe("description layout", () => {
  const text = [
    "Quartz Santé recrute un ingénieur DevOps.", "Poste en CDI.", "",
    "Vos missions :", "- Gérer les clusters", "- Écrire du Terraform", "",
    "Profil recherché", "Bac+5, 2 ans.", "• Kubernetes", "• Docker",
    "Salaire : 42 - 48 k€ brut annuel",
    "Avantages : tickets restaurant, télétravail",
  ].join("\n");

  test("finds the usual sections, their lists and their paragraphs", () => {
    const p = D.parse(text);
    assert.deepEqual(p.sections.map((s) => s.title), [null, "Vos missions", "Profil recherché", "Avantages"]);
    assert.deepEqual(p.sections[0].blocks, [{ p: "Quartz Santé recrute un ingénieur DevOps.\nPoste en CDI." }]);
    assert.deepEqual(p.sections[1].blocks, [{ list: ["Gérer les clusters", "Écrire du Terraform"] }]);
    assert.deepEqual(p.sections[2].blocks[1], { list: ["Kubernetes", "Docker"] });
    assert.deepEqual(p.sections[3].blocks, [{ p: "tickets restaurant, télétravail" }]);
  });

  test("keeps plain paragraphs when no section is named", () => {
    const p = D.parse("Une équipe de huit.\nAstreinte une semaine sur six.\n\nHybride, deux jours sur site.");
    assert.equal(p.sections.length, 1);
    assert.equal(p.sections[0].title, null);
    assert.equal(p.sections[0].blocks.length, 2);
    assert.equal(D.parse("").sections.length, 0);
  });

  test("reads a salary only from an explicit line, word for word", () => {
    assert.equal(D.parse(text).salary, "42 - 48 k€ brut annuel");
    assert.equal(D.parse("Rémunération annuelle : selon profil").salary, "selon profil");
    assert.equal(D.parse("Un salaire attractif et des primes.").salary, null);
  });

  test("hostile text stays text: only section/h3/p/ul/li, strings never parsed", () => {
    const hostile = "Missions :\n- <img src=x onerror=alert(1)>\n<script>alert(2)</script>\n</section><h1>x";
    const calls = [];
    const el = (tag, attrs, kids) => { calls.push({ tag, attrs: Object.keys(attrs || {}) }); return { tag, text: attrs && attrs.text, kids }; };
    const out = D.render(D.parse(hostile), el);
    assert.ok(calls.every((c) => ["section", "h3", "p", "ul", "li"].includes(c.tag)));
    assert.ok(calls.every((c) => c.attrs.every((a) => a === "class" || a === "text")));
    const texts = [];
    const walk = (n) => { if (n.text) texts.push(n.text); (n.kids || []).forEach(walk); };
    out.forEach(walk);
    assert.ok(texts.includes("<img src=x onerror=alert(1)>"));
    assert.ok(texts.some((t) => t.includes("<script>alert(2)</script>")));
  });
});

describe("M24 explanation lines", () => {
  test("the title family and the profile weighting add up in the ledger", () => {
    const b = S.breakdown({ score: 84, section: "strong", explanations: [
      "Profile section: kubernetes (x1.5)", "Matched preferred: kubernetes (+6)",
      "Matched preferred: docker (+3)", "Missed preferred: aws", "Matched negative: sap (-5)",
      "Title relevance: core (+20)",
    ] });
    assert.equal(b.start, 60);
    assert.deepEqual(b.lines.map((l) => [l.kind, l.label, l.value]), [
      ["up", "kubernetes (demandée au profil)", 6], ["up", "docker", 3], ["down", "sap", -5],
      ["up", "titre\u00a0: métier visé", 20],
    ]);
  });

  test("a penalty is a down line and a zero-point family adds no line", () => {
    const other = S.breakdown({ score: 35, explanations: ["Title relevance: other (-15)"] });
    assert.deepEqual(other.lines, [{ kind: "down", label: "titre\u00a0: hors des métiers visés", value: -15 }]);
    assert.equal(other.start, 50);
    assert.deepEqual(S.breakdown({ score: 50, explanations: ["Title relevance: near (+0)"] }).lines, []);
  });
});
