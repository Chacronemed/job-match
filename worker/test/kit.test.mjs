// The answer kit (kit.js, ADR 0023) and the validator of its two model-written answers
// (documents.js): the salary never comes from the model, `manuel` never yields a value.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { buildTargetedRetry, errorTarget, mergeRetry, validateDocument } from "../src/documents.js";
import { answerKit, availabilityText, salaryBenchmark, salaryItem, salaryRangeText } from "../src/kit.js";

const NOW = new Date("2026-11-05T08:00:00Z");
const MASTER = {
  headline: "Ingénieur DevOps", target: "CDI DevOps", available_from: "2027-01-15", mobility: "Mobile en France",
  experiences: [{
    id: "exp1", employer: "Acme Cloud", title: "DevOps (alternance)", start: "2025-01", end: null, location: "Nantes",
    bullets: [{ id: "exp1.b1", text: "Migration de 12 services vers Kubernetes.", tools: ["Kubernetes"] }],
  }],
  projects: [], skills: [{ id: "kubernetes", label: "Kubernetes" }],
  skill_groups: [{ group: "Conteneurs", items: ["Kubernetes"] }],
  education: [], certifications: [], languages: [], extras: [],
};
const OFFER = { key: "ats:greenhouse:acme:1", title: "DevOps Kubernetes", company: "Initech", location: "Paris", description_excerpt: "Kubernetes chez Initech." };
const REMUNERATION = {
  mode: "manuel",
  fourchette: { min: 40000, max: 46000, devise: "€", periode: "brut annuel" },
  reperes: [
    { zone: "Île-de-France", match: ["paris", "ile de france", "hauts de seine"], texte: "42–48 k€ brut annuel" },
    { zone: "Province", match: [], texte: "36–42 k€ brut annuel" },
  ],
};
const CONTENT = {
  language: "fr",
  answers: {
    motivation: { sentences: [{ text: "Ce poste prolonge mon alternance.", sources: [] }] },
    why_company: { sentences: [{ text: "Initech construit une plateforme cloud.", sources: [] }] },
  },
};

describe("answerKit", () => {
  test("the model's two answers, the availability from the master, the fixed answers from apply.yaml", () => {
    const apply = { preavis: "Aucun", remuneration: REMUNERATION, reponses_fixes: [{ label: "Permis B", match: ["permis"], reponse: "Oui" }] };
    const kit = answerKit(CONTENT, MASTER, apply, NOW, "Paris 15e");
    const by = Object.fromEntries(kit.map((i) => [i.label, i]));
    assert.equal(by["Motivation (courte)"].text, "Ce poste prolonge mon alternance.");
    assert.equal(by["Pourquoi cette entreprise"].text, "Initech construit une plateforme cloud.");
    assert.equal(by["Disponibilité"].text, availabilityText(MASTER.available_from, NOW, "fr"));
    assert.equal(by["Disponibilité"].text, "Disponible à partir de janvier 2027");
    assert.equal(by["Mobilité"].text, "Mobile en France");
    assert.equal(by["Préavis"].text, "Aucun");
    assert.deepEqual(by["Permis B"].match, ["permis"]);
    assert.ok(by["Permis B"].copy);
  });

  test("manuel: no salary value anywhere in the kit, nothing to copy, the zone's benchmark in the note", () => {
    const kit = answerKit(CONTENT, MASTER, { remuneration: REMUNERATION }, NOW, "Paris");
    const salary = kit.find((i) => i.key === "salary");
    assert.equal(salary.mode, "manuel");
    assert.equal(salary.text, null);
    assert.equal(salary.copy, false);
    assert.equal(salary.range, undefined);
    assert.match(salary.note, /Repère Île-de-France : 42–48 k€/);
    assert.ok(!JSON.stringify(kit).includes("40000") && !JSON.stringify(kit).includes("40 000"), "the range never leaks in manuel");
  });

  test("no apply.yaml: the salary is manuel, preavis says it is missing; old content says to regenerate", () => {
    const kit = answerKit({ language: "fr" }, MASTER, null, NOW, "Lyon");
    const salary = kit.find((i) => i.key === "salary");
    assert.equal(salary.mode, "manuel");
    assert.equal(salary.text, null);
    assert.equal(kit.find((i) => i.key === "notice").text, null);
    assert.match(kit.find((i) => i.key === "motivation").note, /regénère/);
  });

  test("fourchette: the range as one line, with its numbers for a select", () => {
    const item = salaryItem({ remuneration: { ...REMUNERATION, mode: "fourchette" } }, "Lyon");
    assert.equal(item.text, "40 000 – 46 000 € brut annuel");
    assert.deepEqual(item.range, { min: 40000, max: 46000 });
    assert.equal(salaryRangeText({ min: 38000, max: 38000 }), "38 000 – 38 000 €");
  });

  test("the benchmark: the first zone whose word is in the location, else the default entry", () => {
    assert.equal(salaryBenchmark(REMUNERATION, "Nanterre, Hauts-de-Seine").zone, "Île-de-France");
    assert.equal(salaryBenchmark(REMUNERATION, "Lyon").zone, "Province");
    assert.equal(salaryBenchmark({ reperes: [{ zone: "IDF", match: ["paris"], texte: "x" }] }, "Lyon"), null);
    assert.equal(salaryBenchmark(null, "Paris"), null);
  });
});

function doc(answers) {
  return {
    language: "fr",
    profile: "Ingénieur DevOps orienté Kubernetes. Je cherche un CDI DevOps. Disponible à partir de janvier 2027.",
    selected_bullets: [{ id: "exp1.b1", text: "Migration de 12 services vers Kubernetes." }],
    skill_groups: [{ group: "Conteneurs", items: ["Kubernetes"] }],
    headline_techs: ["Kubernetes"],
    letter: { paragraphs: [
      { sentences: [{ text: "Votre offre chez Initech me parle.", sources: [] }] },
      { sentences: [{ text: "En alternance chez Acme Cloud, j'ai migré 12 services vers Kubernetes.", sources: ["exp1.b1"] }] },
      { sentences: [{ text: "Disponible à partir de janvier 2027, je serais heureux d'en discuter.", sources: [] }] },
    ] },
    answers,
  };
}
const ok = () => ({
  motivation: { sentences: [{ text: "Chez Acme Cloud, j'ai migré 12 services vers Kubernetes.", sources: ["exp1.b1"] }] },
  why_company: { sentences: [{ text: "Initech construit une plateforme cloud.", sources: [] }] },
});
const v = (d) => validateDocument(d, MASTER, OFFER, "fr", { today: NOW });
const one = (text, sources = []) => ({ sentences: [{ text, sources }] });

describe("validateDocument: the answers", () => {
  test("faithful answers pass", () => {
    assert.deepEqual(v(doc(ok())), []);
  });

  test("a missing answers object or a third key is a bad shape", () => {
    const none = doc(ok());
    delete none.answers;
    assert.deepEqual(v(none), ["bad_shape: keys headline_techs,language,letter,profile,selected_bullets,skill_groups"]);
    assert.deepEqual(v(doc({ ...ok(), salary: one("x") })), ["bad_shape: field types"]);
  });

  test("an invented number, an unsourced tool or an unknown employer is refused, as in the letter", () => {
    const errs = v(doc({ ...ok(), motivation: one("J'ai migré 40 services vers Kubernetes chez Globex.") }));
    assert.ok(errs.includes("invented_number: answer motivation sentence 1 has 40"), errs.join("\n"));
    assert.ok(errs.some((e) => e.startsWith("unsourced_tool: answer motivation sentence 1 names kubernetes")), errs.join("\n"));
    assert.ok(errs.includes("unknown_name: answer motivation sentence 1 names Globex"), errs.join("\n"));
  });

  test("600 characters at most, three sentences at most", () => {
    const long = "J'aime l'automatisation des plateformes. ".repeat(16);
    assert.ok(v(doc({ ...ok(), motivation: one(long.trim()) })).some((e) => e.startsWith("too_long: answer motivation")));
    const four = { sentences: [1, 2, 3, 4].map(() => ({ text: "J'aime ce poste.", sources: [] })) };
    assert.ok(v(doc({ ...ok(), motivation: four })).includes("bad_shape: answer motivation has 1 to 3 sentences"));
  });

  test("no availability, salary nor notice in the model's answers: those come from the master and apply.yaml", () => {
    for (const text of ["Je suis disponible tout de suite.", "Mes prétentions sont raisonnables.", "Mon salaire importe peu.", "Sans préavis."]) {
      assert.ok(v(doc({ ...ok(), motivation: one(text) })).some((e) => e.startsWith("answer_scope: answer motivation")), text);
    }
  });

  test("why_company names the offer's company", () => {
    assert.ok(v(doc({ ...ok(), why_company: one("Cette entreprise construit une plateforme cloud.") })).includes("answer_company: answer why_company does not name Initech"));
  });

  test("an answer error is retried alone and merged back in place", () => {
    const bad = doc({ ...ok(), motivation: one("J'ai migré 40 services.") });
    const errs = v(bad);
    assert.deepEqual(errs.map((e) => errorTarget(e).kind), ["answer"]);
    assert.match(buildTargetedRetry(bad, errs), /answer motivation : \[\{"text":"J'ai migré 40 services."/);
    const fixed = mergeRetry(bad, { profile: "", bullets: [], sentences: [], skill_groups: [], headline_techs: [], answers: [{ name: "motivation", sentences: [{ text: "J'aime ce poste.", sources: [] }] }] });
    assert.equal(fixed.answers.motivation.sentences[0].text, "J'aime ce poste.");
    assert.deepEqual(fixed.answers.why_company, bad.answers.why_company);
    assert.deepEqual(v(fixed), []);
  });
});
