// Application documents (documents.js, ADR 0017): the prompt never carries a contact detail,
// the validator refuses what the master does not hold, the cron takes five pending rows,
// respects the budget and the credit, and the routes follow the Access rules.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { before, beforeEach, describe, test } from "node:test";

import { resetJwksCache } from "../src/auth.js";
import {
  allowedSkills,
  BATCH_SIZE,
  buildSystem,
  availabilityText,
  buildTargetedRetry,
  buildUser,
  headlineCandidates,
  costMicroUsd,
  errorTarget,
  DEFAULT_ESTIMATE_PER_DOCUMENT_USD,
  estimatePerDocument,
  mergeRetry,
  RETRY_SCHEMA,
  cvLayout,
  detectLanguage,
  DOCUMENT_SCHEMA,
  DOCUMENTS_CRON,
  DOCUMENTS_MODEL,
  listDocuments,
  runDocuments,
  spentThisMonth,
  STUCK_MINUTES,
  validateDocument,
} from "../src/documents.js";
import worker, { runDocumentsScheduled } from "../src/index.js";
import { env, fakeAssets, fakeD1, fakeR2, identityProvider, request } from "./helpers.mjs";

const NOW = new Date("2026-11-01T08:10:00Z");
const KEY = "france_travail:AAA111";

// A synthetic master, and a contact sheet full of traps the model must never see.
const MASTER = {
  headline: "Ingénieur DevOps — Kubernetes, Terraform",
  target: "CDI DevOps / Cloud",
  available_from: "2027-01-15",
  mobility: "ouvert à la mobilité",
  experiences: [
    {
      id: "exp1", employer: "Acme Cloud", title: "DevOps (alternance)", start: "2025-01", end: null, location: "Nantes",
      bullets: [
        { id: "exp1.b1", text: "Migration de 12 services vers Kubernetes (GKE), 30 merge requests par mois.", tools: ["Kubernetes", "GKE", "GitLab"] },
        { id: "exp1.b2", text: "Automatisation en Python et Bash.", tools: ["Python", "Bash"] },
      ],
    },
    {
      id: "exp2", employer: "Globex", title: "Stagiaire", start: "2024-05", end: "2024-07", location: "Lyon",
      bullets: [
        { id: "exp2.b1", text: "Déploiement sur AWS avec Terraform.", tools: ["AWS", "Terraform"] },
        { id: "exp2.b2", text: "Observabilité Prometheus et Grafana.", tools: ["Prometheus", "Grafana"] },
      ],
    },
  ],
  projects: [{ id: "proj1", name: "Parking", bullets: [{ id: "proj1.b1", text: "IoT et Python.", tools: ["Python"] }] }],
  skills: [
    { id: "kubernetes", label: "Kubernetes (GKE)" }, { id: "terraform", label: "Terraform" },
    { id: "python", label: "Python" }, { id: "aws", label: "AWS" }, { id: "gcp", label: "Google Cloud Platform" },
    { id: "java", label: "Java" }, { id: "prometheus", label: "Prometheus" },
  ],
  skill_groups: [
    { group: "Cloud", items: ["Google Cloud Platform (GKE, IAM)", "AWS (EC2, S3)"] },
    { group: "Conteneurs", items: ["Kubernetes (GKE)", "Helm"] },
    { group: "Développement", items: ["Python", "JavaScript / TypeScript"] },
  ],
  education: [{ degree: "Ingénieur", school: "ENSIAS", location: "Rabat", start: "2022-09", end: "2025-06" }],
  certifications: [],
  languages: [{ name: "Français", level: "bilingue" }],
  extras: [],
};
const CONTACT = {
  first_name: "Jean", last_name: "Trapmarker", title: "DevOps", email: "jean.trap@example.com",
  phone: "+33 6 12 34 56 78", linkedin: "linkedin.com/in/trapjean", github: "github.com/trapjean",
  location: "Lyon-Trapville",
};
const TRAPS = ["Trapmarker", "jean.trap@example.com", "+33 6 12 34 56 78", "trapjean", "Trapville"];

const OFFER = {
  key: KEY, title: "Ingénieur DevOps Kubernetes", company: "Initech", location: "Paris", contract: "CDI",
  score: 88, description_excerpt: "Nous cherchons un ingénieur DevOps pour nos clusters Kubernetes (GKE) et Helm sur notre plateforme GCP (Google Cloud Platform). Vous rejoindrez une équipe de 8 personnes.",
};

const GOOD_ANSWERS = () => ({
  motivation: { sentences: [
    { text: "Ce poste DevOps sur Kubernetes prolonge mon alternance chez Acme Cloud.", sources: ["exp1.b1"] },
    { text: "J'y apporterais mon goût de l'automatisation.", sources: [] },
  ] },
  why_company: { sentences: [{ text: "Initech construit une plateforme cloud, le cadre que je cherche.", sources: [] }] },
});

function good(overrides = {}) {
  return {
    language: "fr",
    profile: "Ingénieur DevOps orienté Kubernetes et GCP. Je cherche un CDI DevOps / Cloud. Disponible à partir de janvier 2027.",
    selected_bullets: [
      { id: "exp1.b1", text: "Migration de 12 services vers Kubernetes sur GKE, 30 merge requests par mois." },
      { id: "exp2.b1", text: "Déploiement AWS avec Terraform." },
    ],
    skill_groups: [
      { group: "Conteneurs", items: ["Kubernetes (GKE)", "Helm"] },
      { group: "Cloud", items: ["Google Cloud Platform (GKE, IAM)", "AWS (EC2, S3)"] },
    ],
    headline_techs: ["Kubernetes", "GKE", "GCP", "Google Cloud Platform", "Helm"],
    letter: {
      paragraphs: [
        { sentences: [{ text: "Votre offre chez Initech correspond à ce que je cherche.", sources: [] }] },
        { sentences: [
          { text: "En alternance chez Acme Cloud, j'ai migré 12 services vers Kubernetes.", sources: ["exp1.b1"] },
          { text: "Lors de mon stage, j'ai mis en place Prometheus et Grafana.", sources: ["exp2.b2"] },
        ] },
        { sentences: [{ text: "Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous.", sources: [] }] },
      ],
    },
    answers: GOOD_ANSWERS(),
    ...overrides,
  };
}

const CONCL_SENTENCE = "Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous.";
const letter = (...paragraphs) => ({
  paragraphs: paragraphs.map((p) => ({ sentences: p.map(([text, sources]) => ({ text, sources: sources || [] })) })),
});

// The Claude API double: a queue of {status, body}, documents or Errors.
function anthropic(answers) {
  const calls = [];
  const handler = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    const next = answers.length ? answers.shift() : good();
    if (next instanceof Error) throw next;
    if (next && typeof next.status === "number") {
      return new Response(JSON.stringify(next.body || {}), { status: next.status });
    }
    const text = typeof next === "string" ? next : JSON.stringify(next);
    return new Response(
      JSON.stringify({
        content: [{ type: "text", text }],
        stop_reason: "end_turn",
        usage: { input_tokens: 2000, cache_read_input_tokens: 4000, output_tokens: 1500 },
      }),
      { status: 200 },
    );
  };
  return { calls, handler };
}

let idp;
let db;
let docs;
let logged;

before(async () => {
  idp = await identityProvider();
});

beforeEach(() => {
  resetJwksCache();
  idp.hosts = {};
  db = fakeD1();
  docs = fakeR2({ "master/cv_master.json": MASTER, "master/contact.json": CONTACT });
  logged = [];
  console.log = (...args) => logged.push(args.map(String).join(" "));
});

function docEnv(overrides = {}) {
  return env(db, {
    ASSETS: fakeAssets({ "/data.json": { thresholds: { strong: 80, min_score: 55 }, jobs: [OFFER], tracked: [] } }),
    ANTHROPIC_API_KEY: "sk-ant-test-secret",
    DOCS: docs,
    ...overrides,
  });
}

function keep(key = KEY, status = "to_apply") {
  db.raw.prepare("INSERT INTO applications (job_key, status, updated_at) VALUES (?, ?, ?)").run(key, status, NOW.toISOString());
}

function pending(key = KEY, version = 1) {
  db.raw
    .prepare("INSERT INTO documents (job_key, version, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)")
    .run(key, version, NOW.toISOString(), NOW.toISOString());
}

function row(key = KEY) {
  return db.raw.prepare("SELECT * FROM documents WHERE job_key = ? ORDER BY version DESC").get(key);
}

const run = (e = docEnv(), opts = {}) => runDocuments(e, { fetch: globalThis.fetch, now: NOW, ...opts });

describe("prompt and schema", () => {
  test("the schema is strict and asks for the five fields", () => {
    assert.equal(DOCUMENT_SCHEMA.additionalProperties, false);
    assert.deepEqual(DOCUMENT_SCHEMA.required, ["language", "profile", "selected_bullets", "skill_groups", "headline_techs", "letter", "answers"]);
    assert.ok(!JSON.stringify(DOCUMENT_SCHEMA).includes("maxLength"), "lengths are checked in code");
  });

  test("the user message names the master skills the offer cites, for headline_techs", () => {
    const ctx = { today: NOW, availability: "Disponible à partir de janvier 2027", finished: [], candidates: headlineCandidates(MASTER, OFFER) };
    const text = buildUser(OFFER, "fr", ctx);
    assert.ok(text.includes("Technologies du maître que l'offre cite (pour headline_techs) : Kubernetes (GKE), Google Cloud Platform."), text);
    const bare = buildUser({ ...OFFER, description_excerpt: "Rien de technique." }, "fr", { ...ctx, candidates: [] });
    assert.ok(bare.includes("(pour headline_techs) : aucune."), bare);
  });

  test("the system block is cached, stable and carries the master only", () => {
    const a = buildSystem(MASTER);
    const b = buildSystem(JSON.parse(JSON.stringify({ ...MASTER, headline: MASTER.headline })));
    assert.equal(a[0].text, b[0].text);
    assert.deepEqual(a[0].cache_control, { type: "ephemeral" });
    assert.ok(a[0].text.includes("exp1.b1"));
    for (const t of TRAPS) assert.ok(!a[0].text.includes(t), t);
  });

  test("the language follows the offer", () => {
    assert.equal(detectLanguage("Nous recherchons un ingénieur pour la plateforme et les clusters"), "fr");
    assert.equal(detectLanguage("We are looking for an engineer to join our platform team and you will"), "en");
    assert.equal(detectLanguage(""), "fr");
  });

  test("allowed skills include tools and split group items", () => {
    const s = allowedSkills(MASTER);
    for (const t of ["kubernetes", "gke", "gitlab", "google cloud platform", "iam", "aws", "ec2"]) assert.ok(s.has(t), t);
    assert.ok(!s.has("azure"));
  });
});

describe("validateDocument", () => {
  const v = (doc, master = MASTER, offer = OFFER, language = "fr") => validateDocument(doc, master, offer, language, { today: NOW });

  test("a faithful document passes", () => {
    assert.deepEqual(v(good()), []);
  });

  test("an invented number, skill, employer, phrase or bullet is named", () => {
    const errs = v(good({
      selected_bullets: [
        { id: "exp1.b1", text: "Migration de 15 services vers Kubernetes." },
        { id: "exp9.b9", text: "Rien." },
      ],
      skill_groups: [{ group: "Cloud", items: ["Azure"] }],
      profile: "Ingénieur DevOps chez Hooli à Berlin. Je cherche un CDI, disponible à partir de janvier 2027. Je livre sans régression.",
      letter: letter([["Chez Initech, je serai disponible."]], [["J'ai géré 42 clusters.", ["exp1.b1"]]], [["Merci."]]),
    }));
    assert.ok(errs.some((e) => e.startsWith("invented_number: bullet exp1.b1 has 15")), errs);
    assert.ok(errs.some((e) => e.startsWith("unknown_bullet: exp9.b9")), errs);
    assert.ok(errs.some((e) => e.startsWith("invented_skill: Azure is not an item of Cloud")), errs);
    assert.ok(errs.some((e) => e === "unknown_name: profile names Hooli"), errs);
    assert.ok(errs.some((e) => e === "unknown_name: profile names Berlin"), errs);
    assert.ok(errs.some((e) => e.startsWith("forbidden_phrase: profile")), errs);
    assert.ok(errs.some((e) => e.startsWith("invented_number: letter paragraph 2 sentence 1 has 42")), errs);
    assert.ok(!errs.some((e) => e.includes("Initech")), "the offer's company is allowed");
  });

  test("lengths, counts and the language are checked", () => {
    const errs = v(good({
      language: "en",
      profile: "Une seule phrase.",
      selected_bullets: Array.from({ length: 19 }, () => ({ id: "exp2.b2", text: "Observabilité Prometheus et Grafana." })),
      letter: letter([["a"]], [["b"]]),
    }));
    assert.ok(errs.includes("wrong_language: expected fr"));
    assert.ok(errs.includes("bad_shape: profile has 1 sentences (2 to 3)"));
    assert.ok(errs.includes("too_many_bullets: 19 (1 to 18)"));
    assert.ok(errs.includes("bad_shape: letter has 2 paragraphs (3 to 5)"));
    assert.ok(errs.some((e) => e.startsWith("unknown_bullet: exp2.b2")), "a bullet used twice");
    const long = v(good({ selected_bullets: [{ id: "exp2.b2", text: "x".repeat(221) }] }));
    assert.ok(long.includes("too_long: bullet exp2.b2"));
    assert.deepEqual(v("nope"), ["bad_shape: not an object"]);
    assert.deepEqual(v({ a: 1 }), ["bad_shape: keys a"]);
  });

  test("a sentence's tools, numbers and context must come from the bullets it cites", () => {
    // The review case: Prometheus belongs to the internship (exp2), not to the apprenticeship.
    let errs = v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["En alternance, j'ai mis en place Prometheus.", ["exp1.b1"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) }));
    assert.ok(errs.some((e) => e.startsWith("unsourced_tool: letter paragraph 2 sentence 1 names prometheus")), errs);
    // The same sentence citing the right bullet still names the wrong context.
    errs = v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["En alternance, j'ai mis en place Prometheus.", ["exp2.b2"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) }));
    assert.ok(errs.some((e) => e === "wrong_context: letter paragraph 2 sentence 1 says « alternance » (exp1) but cites exp2.b2"), errs);
    // An employer named without a source, a number from another bullet, an unknown source id.
    errs = v(good({ letter: letter(
      [["Chez Globex, j'ai beaucoup appris."]],
      [["Chez Acme Cloud, j'ai migré 12 services.", ["exp1.b2"]], ["Et 30 merge requests par mois.", ["exp9.b9"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) }));
    assert.ok(errs.some((e) => e.startsWith("wrong_context: letter paragraph 1 sentence 1 says « globex » (exp2) but cites nothing")), errs);
    assert.ok(errs.some((e) => e.startsWith("invented_number: letter paragraph 2 sentence 1 has 12")), errs);
    assert.ok(errs.some((e) => e.startsWith("unknown_bullet: letter paragraph 2 sentence 2 cites exp9.b9")), errs);
    // Headline tools and the availability need no source.
    assert.deepEqual(v(good({ letter: letter(
      [["Votre offre DevOps m'intéresse."]],
      [["Kubernetes est au cœur de mon parcours.", []]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) })), []);
  });

  test("skill groups: the master's names and items, 7 at most, the offer's group first, no dev language unless asked", () => {
    const cloud = { group: "Cloud", items: ["AWS (EC2, S3)"] };
    let errs = v(good({ skill_groups: Array.from({ length: 8 }, () => cloud) }));
    assert.ok(errs.includes("too_many_skills: 8 groups (1 to 7)"), errs);
    errs = v(good({ skill_groups: [{ group: "Conteneurs", items: ["Kubernetes (GKE)"] }, { group: "Développement", items: ["JavaScript / TypeScript"] }] }));
    assert.ok(errs.some((e) => e.startsWith("dev_language: JavaScript / TypeScript names javascript")), errs);
    errs = v(good({ skill_groups: [{ group: "Réseau", items: ["TCP/IP"] }] }));
    assert.ok(errs.includes("invented_skill: group Réseau is not in the master"), errs);
    errs = v(good({ skill_groups: [{ group: "Conteneurs", items: ["Kubernetes"] }] }));
    assert.ok(errs.includes("invented_skill: Kubernetes is not an item of Conteneurs"), "items are copied verbatim");
    errs = v(good({ skill_groups: [{ group: "Développement", items: ["Python"] }, { group: "Conteneurs", items: ["Kubernetes (GKE)"] }] }));
    assert.ok(errs.includes("skills_order: the first group Développement holds nothing the offer asks for"), errs);
    const jsOffer = { ...OFFER, description_excerpt: OFFER.description_excerpt + " Vous maîtrisez JavaScript." };
    assert.deepEqual(v(good({ skill_groups: [{ group: "Conteneurs", items: ["Kubernetes (GKE)"] }, { group: "Développement", items: ["JavaScript / TypeScript"] }] }), MASTER, jsOffer), []);
  });

  test("the title line: up to 6 technologies the offer names, 5 at least when it names 5", () => {
    // OFFER names two master skills (Kubernetes (GKE), Google Cloud Platform); their forms count too
    assert.deepEqual(headlineCandidates(MASTER, OFFER), ["Kubernetes (GKE)", "Google Cloud Platform"]);
    let errs = v(good({ headline_techs: ["Kubernetes"] }));
    assert.ok(errs.includes("headline_techs: 1 technologies (2 to 6, the offer names 2)"), errs);
    assert.deepEqual(v(good({ headline_techs: ["Kubernetes", "GKE"] })), []);
    errs = v(good({ headline_techs: ["Kubernetes", "GKE", "GCP", "Helm", "Azure"] }));
    assert.ok(errs.includes("headline_techs: Azure is not in the master"), errs);
    errs = v(good({ headline_techs: ["Kubernetes", "GKE", "GCP", "Helm", "Terraform"] }));
    assert.ok(errs.includes("headline_techs: Terraform is not in the offer"), errs);
    errs = v(good({ headline_techs: ["Kubernetes", "GKE", "GCP", "Helm", "kubernetes"] }));
    assert.ok(errs.includes("headline_techs: kubernetes twice"), errs);
    errs = v(good({ headline_techs: ["Kubernetes", "GKE", "GCP", "Helm", "Google Cloud Platform", "kubernetes", "gke"] }));
    assert.ok(errs.includes("headline_techs: 7 technologies (2 to 6, the offer names 2)"), errs);
  });

  // Prod 2026-11-02 (7 rows failed on headline_techs, 14 carried the code): France Travail
  // offers name few master skills. 7766868 named three (Kubernetes, Infrastructure as Code,
  // AWS), 7990644 one (Ansible): five techs were impossible without one absent from the offer.
  test("an offer naming three master skills accepts three headline techs, not two", () => {
    const three = { ...OFFER, description_excerpt: "Ingénieur DevOps AWS confirmé : Kubernetes, infrastructure as code, AWS. Équipe de 6." };
    assert.deepEqual(headlineCandidates(MASTER, three), ["Kubernetes (GKE)", "AWS"]);
    const master = { ...MASTER, skills: [...MASTER.skills, { id: "infrastructure as code", label: "Infrastructure as Code" }] };
    assert.deepEqual(headlineCandidates(master, three), ["Kubernetes (GKE)", "AWS", "Infrastructure as Code"]);
    assert.deepEqual(v(good({ headline_techs: ["Kubernetes", "AWS", "Infrastructure as Code"] }), master, three), []);
    let errs = v(good({ headline_techs: ["Kubernetes", "AWS"] }), master, three);
    assert.ok(errs.includes("headline_techs: 2 technologies (3 to 6, the offer names 3)"), errs);
    errs = v(good({ headline_techs: ["Kubernetes", "AWS", "Infrastructure as Code", "Terraform"] }), master, three);
    assert.ok(errs.includes("headline_techs: Terraform is not in the offer"), errs);
    errs = v(good({ headline_techs: ["Kubernetes", "AWS", "Infrastructure as Code", "GKE", "GKE", "GKE", "GKE"] }), master, three);
    assert.ok(errs.includes("headline_techs: 7 technologies (3 to 6, the offer names 3)"), errs);
  });

  test("an offer naming one master skill accepts that one alone, never none", () => {
    const one = { ...OFFER, title: "Ingénieur(e) DevOps - Toulon (H/F)", description_excerpt: "Vous automatisez les déploiements avec Ansible au sein d'une équipe agile." };
    const master = { ...MASTER, skills: [...MASTER.skills, { id: "ansible", label: "Ansible" }] };
    const headline = (doc, offer) => v(doc, master, offer).filter((e) => e.startsWith("headline_techs"));
    assert.deepEqual(headlineCandidates(master, one), ["Ansible"]);
    assert.deepEqual(headline(good({ headline_techs: ["Ansible"] }), one), []);
    const errs = headline(good({ headline_techs: [] }), one);
    assert.deepEqual(errs, ["headline_techs: 0 technologies (1 to 6, the offer names 1)"]);
    const none = { ...OFFER, title: "Responsable d'exploitation", description_excerpt: "Responsable d'exploitation logistique." };
    assert.deepEqual(headlineCandidates(master, none), []);
    assert.deepEqual(headline(good({ headline_techs: [] }), none), []);
  });

  test("every experience with four bullets or more keeps at least four", () => {
    const rich = JSON.parse(JSON.stringify(MASTER));
    rich.experiences[0].bullets.push(
      { id: "exp1.b3", text: "Observabilité Prometheus.", tools: ["Prometheus"] },
      { id: "exp1.b4", text: "Pipelines GitLab.", tools: ["GitLab"] },
      { id: "exp1.b5", text: "Administration Linux.", tools: ["Linux"] },
    );
    let errs = v(good(), rich);
    assert.ok(errs.includes("too_few_bullets: exp1 keeps 1 of 5 bullets (4 at least)"), errs);
    const doc = good({ selected_bullets: [
      { id: "exp1.b1", text: "Migration de 12 services vers Kubernetes sur GKE, 30 merge requests par mois." },
      { id: "exp1.b2", text: "Scripts Python et Bash." }, { id: "exp1.b3", text: "Prometheus." }, { id: "exp1.b4", text: "GitLab." },
      { id: "exp2.b1", text: "Déploiement AWS avec Terraform." },
    ] });
    assert.deepEqual(v(doc, rich).filter((e) => e.startsWith("too_few")), []);
  });

  test("an experience that is over is told in the past tense, in the letter and in the profile", () => {
    // exp2 (the internship) ended in 2024-07: the present is refused when it is what the sentence tells.
    let errs = v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["Lors de mon stage, je déploie sur AWS avec Terraform.", ["exp2.b1"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) }));
    assert.ok(errs.some((e) => e.startsWith("wrong_tense: letter paragraph 2 sentence 1")), errs);
    errs = v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["Chez Globex, j'assure actuellement le déploiement sur AWS.", ["exp2.b1"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) }));
    assert.ok(errs.some((e) => e.startsWith("wrong_tense:")), errs);
    // exp1 is ongoing (no end): the present is right there.
    assert.deepEqual(v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["En alternance chez Acme Cloud, j'automatise en Python et Bash.", ["exp1.b2"]]],
      [["Disponible à partir de janvier 2027, je serais heureux d'en discuter avec vous."]],
    ) })), []);
    // Once exp1 is over too, a present-tense profile is refused.
    const over = { ...MASTER, experiences: [{ ...MASTER.experiences[0], end: "2026-06" }, MASTER.experiences[1]] };
    errs = v(good({ profile: "Ingénieur DevOps : je gère des clusters Kubernetes. Je cherche un CDI. Disponible à partir de janvier 2027." }), over);
    assert.ok(errs.includes("wrong_tense: the profile uses the present for experiences that are over"), errs);
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps : j'ai géré des clusters Kubernetes. Je cherche un CDI. Disponible à partir de janvier 2027." }), over), []);
  });

  test("the availability sentence comes from available_from and today, and must be quoted", () => {
    assert.equal(availabilityText("2027-01-15", NOW, "fr"), "Disponible à partir de janvier 2027");
    assert.equal(availabilityText("2027-01-15", NOW, "en"), "Available from January 2027");
    assert.equal(availabilityText("2026-11-01", NOW, "fr"), "Disponible immédiatement");
    assert.equal(availabilityText("2026-10-01", NOW, "en"), "Available immediately");
    assert.equal(availabilityText(undefined, NOW, "fr"), "Disponible immédiatement");
    let errs = v(good({ profile: "Ingénieur DevOps orienté Kubernetes. Je cherche un CDI DevOps / Cloud." }));
    assert.ok(errs.some((e) => e.startsWith("availability_missing: the profile must carry")), errs);
    errs = v(good({ profile: "Ingénieur DevOps orienté Kubernetes. Disponible à partir de janvier 2027. Ou disponible plus tôt." }));
    assert.ok(errs.includes("availability_missing: the profile makes another availability claim"), errs);
    const now = { ...MASTER, available_from: "2026-10-01" };
    errs = v(good({ profile: "Ingénieur DevOps orienté Kubernetes. Je cherche un CDI. Disponible immédiatement." }), now);
    assert.deepEqual(errs.filter((e) => e.startsWith("availability_missing")), []);
  });

  test("the availability is a full sentence in the profile and sits once, integrated, in the conclusion", () => {
    let errs = v(good({ profile: "Ingénieur DevOps orienté Kubernetes. Je cherche un CDI. Disponible à partir de janvier 2027" }));
    assert.ok(errs.includes("availability_missing: the profile must end the availability sentence with a period"), errs);
    errs = v(good({ letter: letter([["Votre offre m'intéresse."]], [["Kubernetes est au cœur de mon parcours."]], [["Disponible à partir de janvier 2027."]]) }));
    assert.ok(errs.some((e) => e.startsWith("availability_misplaced: letter paragraph 3 sentence 1 is the availability alone")), errs);
    errs = v(good({ letter: letter([["Disponible à partir de janvier 2027, votre offre m'intéresse."]], [["Kubernetes est au cœur de mon parcours."]], [["Je serais heureux d'en discuter."]]) }));
    assert.ok(errs.some((e) => e.startsWith("availability_misplaced: letter paragraph 1 sentence 1 carries the availability outside")), errs);
    errs = v(good({ letter: letter([["Votre offre m'intéresse."]], [["Kubernetes est au cœur de mon parcours."]], [["Je serais heureux d'en discuter."]]) }));
    assert.ok(errs.includes("availability_misplaced: the letter says « Disponible à partir de janvier 2027 » 0 times (once, in the conclusion)"), errs);
  });

  test("the profile keeps the real chronology when it uses a time connector", () => {
    // exp2 (Globex, 2024) came before exp1 (Acme Cloud, 2025): "Acme puis Globex" is false.
    let errs = v(good({ profile: "Ingénieur DevOps formé chez Acme Cloud puis chez Globex. Je cherche un CDI. Disponible à partir de janvier 2027." }));
    assert.ok(errs.some((e) => e.startsWith("profile_chronology: the profile names exp1 then exp2")), errs);
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps formé chez Globex puis chez Acme Cloud. Je cherche un CDI. Disponible à partir de janvier 2027." })), []);
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps formé chez Acme Cloud et chez Globex. Je cherche un CDI. Disponible à partir de janvier 2027." })), []);
  });

  // Prod 2026-11-02 (7 rows failed on profile_chronology): the real master has an "alternance"
  // after a "projet de fin d'études" and two "Stagiaire" experiences. "Y, après X" with Y the
  // most recent is true; one shared word cannot order two experiences.
  test("« après » and « avant » are read with their sense, and a shared context word orders nothing", () => {
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps en alternance chez Acme Cloud, après un stage chez Globex. Je cherche un CDI. Disponible à partir de janvier 2027." })), []);
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps formé chez Globex avant Acme Cloud. Je cherche un CDI. Disponible à partir de janvier 2027." })), []);
    const twoInterns = JSON.parse(JSON.stringify(MASTER));
    twoInterns.experiences.push({ id: "exp3", employer: "Hooli", title: "Stagiaire DevOps", start: "2023-06", end: "2023-08", location: "Lyon", bullets: [{ id: "exp3.b1", text: "Scripts Bash.", tools: ["Bash"] }] });
    assert.deepEqual(v(good({ profile: "Ingénieur DevOps : deux stages, puis une alternance chez Acme Cloud. Je cherche un CDI. Disponible à partir de janvier 2027." }), twoInterns), []);
    const errs = v(good({ profile: "Ingénieur DevOps formé chez Acme Cloud, puis stagiaire chez Globex. Je cherche un CDI. Disponible à partir de janvier 2027." }), twoInterns);
    assert.ok(errs.some((e) => e.startsWith("profile_chronology: the profile names exp1 then exp2")), errs);
  });

  test("the last paragraph is the conclusion alone", () => {
    const errs = v(good({ letter: letter(
      [["Votre offre m'intéresse."]],
      [["Kubernetes est au cœur de mon parcours."]],
      [["Chez Globex, j'ai déployé sur AWS avec Terraform.", ["exp2.b1"]], [CONCL_SENTENCE]],
    ) }));
    assert.ok(errs.includes("conclusion_facts: letter paragraph 3 sentence 1 cites exp2.b1 but the last paragraph is the conclusion alone"), errs);
  });

  test("the skills the offer asks for and the chosen bullets prove come first", () => {
    // The offer names Kubernetes and GCP; the chosen bullets hold Kubernetes and Terraform: kubernetes is proven.
    assert.deepEqual(v(good()), []);
  });

  test("error targets and the targeted retry text", () => {
    assert.deepEqual(errorTarget("invented_number: letter paragraph 2 sentence 1 has 42"), { kind: "sentence", paragraph: 2, index: 1 });
    assert.deepEqual(errorTarget("too_long: bullet exp1.b1"), { kind: "bullet", id: "exp1.b1" });
    assert.deepEqual(errorTarget("invented_skill: azure is not a catalog id"), { kind: "skills" });
    assert.deepEqual(errorTarget("profile_address: the profile speaks to the reader"), { kind: "profile" });
    assert.deepEqual(errorTarget("unknown_name: profile names Hooli"), { kind: "profile" });
    assert.deepEqual(errorTarget("bad_shape: letter has 2 paragraphs (3 to 5)"), { kind: "document" });
    assert.deepEqual(errorTarget("wrong_language: expected fr"), { kind: "document" });
    const text = buildTargetedRetry(good(), ["invented_number: letter paragraph 2 sentence 1 has 42", "too_long: bullet exp2.b1"]);
    assert.ok(text.includes("sentence paragraph 2 index 1 : « En alternance chez Acme Cloud"));
    assert.ok(text.includes("bullet exp2.b1 : « Déploiement AWS avec Terraform. »"));
    assert.ok(!text.includes("Votre offre chez Initech"));
    const merged = mergeRetry(good(), { profile: "", bullets: [{ id: "exp2.b1", text: "AWS." }], sentences: [{ paragraph: 2, index: 1, text: "Nouveau.", sources: ["exp1.b1"] }], skill_groups: [], headline_techs: [] });
    assert.equal(merged.profile, good().profile);
    assert.equal(merged.selected_bullets[1].text, "AWS.");
    assert.deepEqual(merged.letter.paragraphs[1].sentences[0], { text: "Nouveau.", sources: ["exp1.b1"] });
    assert.deepEqual(merged.skill_groups, good().skill_groups);
    assert.deepEqual(errorTarget("headline_techs: Azure is not in the master"), { kind: "headline" });
  });

  test("the profile never speaks to the reader", () => {
    const errs = v(good({ profile: "Ingénieur DevOps prêt à construire votre plateforme. Je cherche un CDI. Disponible à partir de janvier 2027." }));
    assert.ok(errs.includes("profile_address: the profile speaks to the reader (vous, votre, vos)"), errs);
  });

  test("salutations, closings and signatures are the template's job", () => {
    const errs = v(good({ letter: letter(
      [["Madame, Monsieur, votre offre m'intéresse."]],
      [["Kubernetes est au cœur de mon parcours."]],
      [["Cordialement."], ["Jean."]],
    ) }));
    assert.ok(errs.includes("letter_formula: letter paragraph 1 sentence 1 is a salutation"), errs);
    assert.ok(errs.includes("letter_formula: letter paragraph 3 sentence 1 is a closing or a signature"), errs);
  });

  test("the CV layout keeps experiences in reverse chronological order, bullets in the model's order inside", () => {
    const doc = good({ selected_bullets: [
      { id: "exp2.b1", text: "AWS." }, { id: "proj1.b1", text: "IoT." }, { id: "exp1.b2", text: "Scripts." }, { id: "exp1.b1", text: "K8s." },
    ] });
    const cv = cvLayout(MASTER, doc);
    assert.deepEqual(cv.experiences.map((e) => [e.id, e.bullets.map((b) => b.id)]), [["exp1", ["exp1.b2", "exp1.b1"]], ["exp2", ["exp2.b1"]]]);
    assert.deepEqual(cv.experiences.map((e) => e.start), ["2025-01", "2024-05"]);
    assert.deepEqual(cv.projects.map((p) => [p.id, p.bullets.map((b) => b.text)]), [["proj1", ["IoT."]]]);
  });
});

describe("runDocuments", () => {
  test("a pending row becomes ready: content.json in R2, usage and cost in D1, no contact in the request", async () => {
    keep();
    pending();
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run();
    assert.equal(r.outcome, "ok");
    assert.deepEqual([r.counters.taken, r.counters.ready, r.counters.failed], [1, 1, 0]);
    assert.equal(api.calls.length, 1);
    const sent = JSON.stringify(api.calls[0].body);
    for (const t of TRAPS) assert.ok(!sent.includes(t), "contact leaked: " + t);
    assert.equal(api.calls[0].body.model, DOCUMENTS_MODEL);
    assert.equal(api.calls[0].body.output_config.format.type, "json_schema");
    assert.equal(api.calls[0].init.headers["x-api-key"], "sk-ant-test-secret");
    assert.ok(api.calls[0].body.messages[0].content.includes("<offre>"));
    const d = row();
    assert.deepEqual([d.status, d.language, d.model, d.attempts, d.tokens_in, d.tokens_out], ["ready", "fr", DOCUMENTS_MODEL, 1, 6000, 1500]);
    assert.equal(d.cost_micro_usd, 6000 * 2 + 1500 * 10);
    assert.equal(d.content_key, `docs/${KEY}/v1/content.json`);
    const content = JSON.parse(docs.store.get(d.content_key));
    assert.equal(content.offer.company, "Initech");
    assert.equal(content.selected_bullets.length, 2);
    assert.deepEqual(content.cv.experiences.map((e) => e.id), ["exp1", "exp2"]);
    assert.equal(content.prompt_version, "6");
    assert.deepEqual(content.skill_groups[0].group, "Conteneurs");
    assert.deepEqual(content.headline_techs.length, 5);
    assert.ok(content.highlights.includes("kubernetes") && content.highlights.includes("gke"), content.highlights);
    assert.equal(content.availability, "Disponible à partir de janvier 2027");
    assert.equal(d.first_errors, "[]");
    const user = api.calls[0].body.messages[0].content;
    assert.ok(user.includes("Date du jour : 2026-11-01") && user.includes("« Disponible à partir de janvier 2027 »"));
    assert.ok(user.includes("exp2 (Globex, fin 2024-07)") && !user.includes("exp1 ("));
    for (const t of TRAPS) assert.ok(!JSON.stringify(content).includes(t), t);
    const usage = db.raw.prepare("SELECT provider, model, calls, tokens_in FROM ai_usage").all();
    assert.deepEqual(usage.map((u) => ({ ...u })), [{ provider: "anthropic", model: DOCUMENTS_MODEL, calls: 1, tokens_in: 6000 }]);
    assert.equal(await spentThisMonth(db, NOW), costMicroUsd({ tokens_in: 6000, tokens_out: 1500 }));
  });

  test("an invented fact is sent back once with the errors, then the row fails with a code", async () => {
    keep();
    pending();
    const bad = good({ skill_groups: [{ group: "Conteneurs", items: ["Kubernetes (GKE)"] }, { group: "Cloud", items: ["Azure"] }] });
    const api = anthropic([bad, { profile: "", bullets: [], sentences: [], skill_groups: bad.skill_groups, headline_techs: [] }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run();
    assert.deepEqual([r.counters.retried, r.counters.failed, r.counters.ready], [1, 1, 0]);
    assert.equal(api.calls.length, 2);
    const retry = api.calls[1].body.messages;
    assert.equal(retry.length, 3);
    assert.equal(retry[1].role, "assistant");
    assert.ok(retry[2].content.includes("invented_skill: Azure"));
    assert.ok(retry[2].content.includes("skill_groups : "));
    assert.ok(!retry[2].content.includes("Votre offre chez Initech"), "accepted sentences are not sent back");
    assert.deepEqual(api.calls[1].body.output_config.format.schema, RETRY_SCHEMA);
    const d = row();
    assert.deepEqual([d.status, d.error_code, d.attempts, d.first_errors], ["failed", "invented_skill", 2, '["invented_skill"]']);
    assert.equal(db.raw.prepare("SELECT calls FROM ai_usage").get().calls, 2);
  });

  test("a corrected retry succeeds; invalid JSON and a refusal have their codes", async () => {
    keep();
    pending();
    let api = anthropic([good({ profile: "Chez Hooli. Je cherche un CDI." }), { profile: good().profile, bullets: [], sentences: [], skill_groups: [], headline_techs: [] }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let r = await run();
    assert.deepEqual([r.counters.retried, r.counters.ready], [1, 1]);
    assert.equal(row().status, "ready");
    const merged = JSON.parse(docs.store.get(row().content_key));
    assert.equal(merged.profile, good().profile);
    assert.equal(merged.letter.paragraphs.length, 3, "the rest of the first answer is kept");

    db = fakeD1();
    keep();
    pending();
    api = anthropic(["not json", "still not"]);
    idp.hosts["api.anthropic.com"] = api.handler;
    r = await run();
    assert.equal(row().error_code, "invalid_json");

    db = fakeD1();
    keep();
    pending();
    api = anthropic([{ status: 200, body: { stop_reason: "refusal", content: [] } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    r = await run();
    assert.equal(api.calls.length, 1, "a refusal is not retried");
    assert.equal(row().error_code, "refused");
  });

  test("a gone decision or a gone offer fails the row without a call", async () => {
    keep("france_travail:BBB", "ignored");
    pending("france_travail:BBB");
    pending("france_travail:CCC"); // never kept
    keep("france_travail:DDD");
    pending("france_travail:DDD"); // kept, but not in data.json
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run();
    assert.equal(api.calls.length, 0);
    assert.deepEqual([r.counters.skipped, r.counters.taken], [3, 0]);
    assert.equal(row("france_travail:BBB").error_code, "decision_gone");
    assert.equal(row("france_travail:CCC").error_code, "decision_gone");
    assert.equal(row("france_travail:DDD").error_code, "offer_gone");
  });

  test("five rows per pass, oldest first; nothing pending is idle and leaves no trace", async () => {
    const jobs = [];
    for (let i = 1; i <= 7; i++) {
      const k = "france_travail:J" + i;
      keep(k);
      pending(k);
      jobs.push({ ...OFFER, key: k });
    }
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const e = docEnv({ ASSETS: fakeAssets({ "/data.json": { jobs, tracked: [] } }) });
    const r = await run(e);
    assert.equal(BATCH_SIZE, 5);
    assert.deepEqual([r.counters.pending, r.counters.taken, r.counters.ready], [7, 5, 5]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE status = 'pending'").get().n, 2);
    assert.equal(row("france_travail:J7").status, "pending");
    const again = await runDocumentsScheduled(e);
    assert.equal(again.outcome, "ok");
    const idle = await runDocumentsScheduled(e);
    assert.equal(idle.outcome, "idle");
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM document_runs").get().n, 1);
    assert.equal(logged.length, 1);
    assert.match(logged[0], /^documents ok \{/);
    for (const s of ["Initech", "Kubernetes", "sk-ant", "exp1"]) assert.ok(!logged[0].includes(s), s);
  });

  test("an offer kept but no longer listed is read from tracked[]", async () => {
    keep();
    pending();
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const e = docEnv({ ASSETS: fakeAssets({ "/data.json": { jobs: [], tracked: [OFFER] } }) });
    const r = await run(e);
    assert.equal(r.counters.ready, 1);
  });

  test("the monthly budget stops the pass and leaves the rows pending", async () => {
    keep();
    pending();
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-11-01', 'anthropic', ?, 10, 20000000, 2000000)").run(DOCUMENTS_MODEL);
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-10-30', 'anthropic', ?, 10, 90000000, 9000000)").run(DOCUMENTS_MODEL);
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run(docEnv({ AI_DOCUMENTS_MONTHLY_USD: "60" }));
    assert.equal(r.outcome, "budget"); // 20M * 2 + 2M * 10 = 60 $ this month; October does not count
    assert.equal(api.calls.length, 0);
    assert.equal(row().status, "pending");
    const ok = await run(docEnv({ AI_DOCUMENTS_MONTHLY_USD: "61" }));
    assert.equal(ok.outcome, "ok");
  });

  test("a spent credit or a 429 leaves the row pending and pauses the cron for six hours; no Workers AI", async () => {
    keep();
    pending();
    const api = anthropic([{ status: 402, body: { error: { type: "billing_error", message: "credit balance too low" } } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const e = docEnv({ AI: { run: async () => { throw new Error("must not be called"); } } });
    const r = await runDocumentsScheduled(e, { fetch: globalThis.fetch, now: NOW });
    assert.deepEqual([r.outcome, r.http_status], ["credit", 402]);
    assert.equal(row().status, "pending");
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM ai_usage").get().n, 0, "a 402 is not billed");
    assert.match(logged[0], /^documents credit http=402 /);
    const later = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = later.handler;
    const paused = await runDocuments(e, { fetch: globalThis.fetch, now: new Date(NOW.getTime() + 5 * 3600 * 1000) });
    assert.equal(paused.outcome, "credit");
    assert.equal(later.calls.length, 0);
    const resumed = await runDocuments(e, { fetch: globalThis.fetch, now: new Date(NOW.getTime() + 7 * 3600 * 1000) });
    assert.equal(resumed.outcome, "ok");
    assert.equal(later.calls.length, 1);
  });

  test("another 4xx stops the pass with its status; a 5xx is retried then the row fails", async () => {
    keep();
    pending();
    let api = anthropic([{ status: 401, body: { error: { message: "invalid x-api-key secret-detail" } } }]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let r = await runDocumentsScheduled(docEnv());
    assert.deepEqual([r.outcome, r.http_status], ["stopped", 401]);
    assert.equal(row().status, "pending");
    assert.ok(!logged.join(" ").includes("secret-detail"));

    db = fakeD1();
    keep();
    pending();
    api = anthropic([{ status: 529, body: {} }, new Error("ECONNRESET")]);
    idp.hosts["api.anthropic.com"] = api.handler;
    r = await run();
    assert.equal(api.calls.length, 2);
    assert.deepEqual([row().status, row().error_code], ["failed", "api_error"]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM ai_usage").get().n, 0);
  });

  test("no master in R2, no bucket, no key: no call", async () => {
    keep();
    pending();
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    assert.equal((await run(docEnv({ DOCS: fakeR2({}) }))).outcome, "no_master");
    assert.equal((await run(docEnv({ DOCS: undefined }))).outcome, "failed");
    assert.equal((await run(docEnv({ ANTHROPIC_API_KEY: undefined }))).outcome, "failed");
    assert.equal(api.calls.length, 0);
    assert.equal(row().status, "pending");
  });

  test("an exception is a failed row without a message; the cron branches on the schedule", async () => {
    keep();
    pending();
    const e = docEnv();
    e.DB = { prepare: () => { throw new Error("boom with a secret"); } };
    const r = await runDocumentsScheduled(e);
    assert.equal(r.outcome, "failed");
    assert.ok(!logged.join(" ").includes("boom"));
    const calls = [];
    const ctx = { waitUntil: (p) => calls.push(p) };
    await worker.scheduled({ cron: DOCUMENTS_CRON }, docEnv(), ctx);
    await worker.scheduled({ cron: "30 7 * * *" }, docEnv({ ASSETS: fakeAssets({}) }), ctx);
    assert.equal(calls.length, 2);
    const results = await Promise.all(calls);
    // No API host registered: the fetch throws twice, the row fails, the pass itself is ok.
    assert.deepEqual([results[0].outcome, results[0].counters.failed], ["ok", 1]);
    assert.equal(results[1].outcome, "no_profile"); // the rerank path, untouched
  });
});

describe("API", () => {
  let token;
  beforeEach(async () => {
    token = await idp.sign();
  });
  const call = (path, opts = {}) => worker.fetch(request(path, { token, ...opts }), docEnv());

  test("Garder creates one pending row, once; Candidature envoyée remembers the ready version", async () => {
    let res = await call(`/api/applications/${KEY}`, { method: "PUT", body: { status: "to_apply" } });
    assert.equal(res.status, 200);
    res = await call(`/api/applications/${KEY}`, { method: "PUT", body: { status: "to_apply" } });
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents").get().n, 1);
    assert.deepEqual([row().version, row().status], [1, "pending"]);
    db.raw.prepare("UPDATE documents SET status = 'ready'").run();
    res = await call(`/api/applications/${KEY}`, { method: "PUT", body: { status: "applied", applied_at: "2026-11-01" } });
    assert.equal(res.status, 200);
    assert.equal(db.raw.prepare("SELECT sent_documents_version FROM applications").get().sent_documents_version, 1);
    res = await call("/api/applications");
    const body = await res.json();
    assert.deepEqual(body.documents.map((d) => [d.job_key, d.version, d.status]), [[KEY, 1, "ready"]]);
    assert.ok(!JSON.stringify(body).includes("content_key"));
  });

  test("regenerate adds a version, 409 while one is pending; GET lists the versions", async () => {
    let res = await call(`/api/documents/${KEY}/regenerate`, { method: "POST" });
    assert.equal(res.status, 201);
    assert.deepEqual(await res.json(), { document: { job_key: KEY, version: 1, status: "pending" } });
    res = await call(`/api/documents/${KEY}/regenerate`, { method: "POST" });
    assert.equal(res.status, 409);
    db.raw.prepare("UPDATE documents SET status = 'failed', error_code = 'invented_skill'").run();
    res = await call(`/api/documents/${KEY}/regenerate`, { method: "POST" });
    assert.equal(res.status, 201);
    res = await call(`/api/documents/${KEY}`);
    const list = (await res.json()).documents;
    assert.deepEqual(list.map((d) => [d.version, d.status, d.error_code]), [[2, "pending", null], [1, "failed", "invented_skill"]]);
    assert.ok(!JSON.stringify(list).includes("_key"));
    assert.deepEqual((await listDocuments(db)).map((d) => d.version), [2]);
  });

  test("GET /api/applications carries the month's budget, rounded to the cent", async () => {
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-11-01', 'anthropic', ?, 3, 500000, 150000)").run(DOCUMENTS_MODEL);
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-10-30', 'anthropic', ?, 10, 90000000, 9000000)").run(DOCUMENTS_MODEL);
    const res = await call("/api/applications");
    const body = await res.json();
    // 500k * 2 + 150k * 10 = 2.5 $ this month; October does not count
    assert.deepEqual(body.documents_budget, { monthly_usd: 60, spent_usd: 2.5, remaining_usd: 57.5, estimate_usd: DEFAULT_ESTIMATE_PER_DOCUMENT_USD });
  });

  test("the estimate is the mean cost of the last 20 billed documents, 0.08 $ without history", async () => {
    assert.equal(DEFAULT_ESTIMATE_PER_DOCUMENT_USD, 0.08);
    assert.equal(await estimatePerDocument(db), 0.08);
    const insert = db.raw.prepare(
      "INSERT INTO documents (job_key, version, status, cost_micro_usd, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?)",
    );
    // 25 old documents at 0.30 $ each, then 20 recent ones at 0.05 $: only the recent count
    for (let i = 0; i < 25; i++) insert.run(`france_travail:OLD${i}`, "ready", 300000, "2026-09-01T00:00:00Z", `2026-09-01T00:00:${String(i).padStart(2, "0")}Z`);
    for (let i = 0; i < 20; i++) insert.run(`france_travail:NEW${i}`, i % 2 ? "failed" : "ready", 50000, "2026-10-01T00:00:00Z", `2026-10-02T00:00:${String(i).padStart(2, "0")}Z`);
    insert.run("france_travail:PEND", "pending", 0, "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"); // unbilled: ignored
    assert.equal(await estimatePerDocument(db), 0.05);
    const body = await (await call("/api/applications")).json();
    assert.equal(body.documents_budget.estimate_usd, 0.05);
  });

  test("POST /api/documents/missing requests a v1 for kept offers without a row, within the budget", async () => {
    keep("france_travail:A1", "to_apply");
    keep("france_travail:B2", "applied");
    keep("france_travail:C3", "interview");
    keep("france_travail:D4", "rejected"); // not kept: never requested
    keep("france_travail:E5", "to_apply");
    db.raw.prepare("INSERT INTO documents (job_key, version, status, error_code, created_at, updated_at) VALUES (?, 1, 'failed', 'invented_number', ?, ?)")
      .run("france_travail:E5", NOW.toISOString(), NOW.toISOString()); // failed: has its own « Regénérer »
    // 59.90 $ spent: room for one document at the default 0.08 $
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-11-01', 'anthropic', ?, 10, 29950000, 0)").run(DOCUMENTS_MODEL);
    let res = await call("/api/documents/missing", { method: "POST" });
    assert.equal(res.status, 200);
    let body = await res.json();
    assert.deepEqual([body.requested, body.skipped_budget, body.remaining_usd], [1, 2, 0.1]);
    assert.deepEqual(body.documents, [{ job_key: "france_travail:A1", version: 1, status: "pending" }]);
    db.raw.prepare("DELETE FROM ai_usage").run();
    res = await call("/api/documents/missing", { method: "POST" });
    body = await res.json();
    assert.deepEqual([body.requested, body.skipped_budget], [2, 0]);
    assert.deepEqual(body.documents.map((d) => d.job_key).sort(), ["france_travail:B2", "france_travail:C3"]);
    res = await call("/api/documents/missing", { method: "POST" }); // idempotent
    assert.deepEqual(await res.json(), { requested: 0, skipped_budget: 0, remaining_usd: 60, documents: [] });
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE status = 'pending'").get().n, 3);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE job_key = 'france_travail:E5'").get().n, 1);
  });

  // An env whose data.json lists these offers too (the pass skips an offer it cannot read).
  function envWith(keys) {
    const jobs = [OFFER, ...keys.map((key) => ({ ...OFFER, key }))];
    return docEnv({ ASSETS: fakeAssets({ "/data.json": { thresholds: { strong: 80, min_score: 55 }, jobs, tracked: [] } }) });
  }

  test("the cron queues the « À candidater » offers without documents itself, five a pass, within the budget", async () => {
    const keys = [0, 1, 2, 3, 4, 5, 6].map((i) => `france_travail:Q${i}`);
    keys.forEach((k) => keep(k, "to_apply"));
    keep("france_travail:APPLIED", "applied"); // the buttons stay manual for the other statuses
    const api = anthropic([good(), good(), good(), good(), good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run(envWith(keys));
    assert.deepEqual([r.outcome, r.counters.queued, r.counters.taken], ["ok", BATCH_SIZE, BATCH_SIZE]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE status = 'ready'").get().n, BATCH_SIZE);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE job_key = 'france_travail:APPLIED'").get().n, 0);
    const next = anthropic([good(), good()]);
    idp.hosts["api.anthropic.com"] = next.handler;
    const r2 = await run(envWith(keys));
    assert.deepEqual([r2.counters.queued, r2.counters.ready], [2, 2]);
    assert.equal((await run(envWith(keys))).outcome, "idle");
  });

  test("over budget the cron queues nothing; a keys pass queues nothing and takes its offer only", async () => {
    keep("france_travail:A1", "to_apply");
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-11-01', 'anthropic', ?, 10, 30000000, 0)").run(DOCUMENTS_MODEL);
    assert.equal((await run()).outcome, "idle");
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents").get().n, 0);
    db.raw.prepare("DELETE FROM ai_usage").run();
    keep("france_travail:B2", "to_apply");
    pending("france_travail:B2");
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await run(envWith(["france_travail:B2"]), { keys: ["france_travail:B2"] });
    assert.deepEqual([r.counters.queued, r.counters.taken, r.counters.ready], [0, 1, 1]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents WHERE job_key = 'france_travail:A1'").get().n, 0);
  });

  test("regenerate runs the pass for that offer right away through ctx.waitUntil", async () => {
    keep();
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const waits = [];
    const res = await worker.fetch(request(`/api/documents/${KEY}/regenerate`, { method: "POST", token }), docEnv({ fonts: null }), { waitUntil: (p) => waits.push(p) });
    assert.equal(res.status, 201);
    assert.equal(waits.length, 1);
    await Promise.all(waits);
    assert.deepEqual([row().status, api.calls.length], ["ready", 1]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM document_runs").get().n, 1);
  });

  test("over budget, /missing requests nothing", async () => {
    keep();
    db.raw.prepare("INSERT INTO ai_usage VALUES ('2026-11-01', 'anthropic', ?, 10, 30000000, 0)").run(DOCUMENTS_MODEL);
    const body = await (await call("/api/documents/missing", { method: "POST" })).json();
    assert.deepEqual([body.requested, body.skipped_budget, body.remaining_usd], [0, 1, 0]);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM documents").get().n, 0);
  });

  test("the routes keep the Access and origin rules", async () => {
    assert.equal((await call("/api/documents/missing", { method: "POST", origin: null })).status, 403);
    assert.equal((await call("/api/documents/missing", { method: "POST", token: null })).status, 401);
    assert.equal((await call("/api/documents/missing")).status, 405);
    assert.equal((await call(`/api/documents/${KEY}`, { token: null })).status, 401);
    assert.equal((await call(`/api/documents/${KEY}/regenerate`, { method: "POST", origin: null })).status, 403);
    assert.equal((await call("/api/documents/not%20a%20key")).status, 400);
    assert.equal((await call(`/api/documents/${KEY}`, { method: "DELETE" })).status, 405);
    assert.equal((await call(`/api/documents/${KEY}/regenerate`)).status, 405);
  });
});

describe("content (ADR 0019: the browser renders)", () => {
  let token;
  beforeEach(async () => {
    token = await idp.sign();
  });
  const call = (path, opts = {}, envOverrides = {}) => worker.fetch(request(path, { token, ...opts }), docEnv(envOverrides));

  test("a ready version serves its content, the master and the contact sheet; nothing else is rendered or stored", async () => {
    keep();
    pending();
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const r = await runDocumentsScheduled(docEnv(), { fetch: globalThis.fetch, now: NOW });
    assert.deepEqual([r.outcome, r.counters.ready, "rendered" in r.counters], ["ok", 1, false]);
    assert.deepEqual([...docs.store.keys()].sort(), ["docs/" + KEY + "/v1/content.json", "master/contact.json", "master/cv_master.json"]);
    assert.equal((await runDocumentsScheduled(docEnv(), { fetch: globalThis.fetch, now: NOW })).outcome, "idle");

    const res = await call(`/api/documents/${KEY}/v1/content.json`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("Content-Type"), "application/json");
    assert.equal(res.headers.get("Cache-Control"), "no-store");
    const body = await res.json();
    assert.deepEqual(Object.keys(body).sort(), ["apply", "contact", "content", "master"]);
    assert.equal(body.apply, null); // no apply.json pushed: the kit shows its notes
    assert.deepEqual([body.content.job_key, body.content.version, body.content.offer.company], [KEY, 1, "Initech"]);
    assert.deepEqual(body.contact, CONTACT);
    assert.equal(body.master.headline, MASTER.headline);
    assert.equal(docs.store.size, 3); // the route stores nothing
    assert.equal((await call(`/api/documents/${KEY}/v2/content.json`)).status, 404);
    assert.equal((await call(`/api/documents/${KEY}/v1/cv.pdf`)).status, 400); // no file route any more: an invalid key
    assert.equal((await call(`/api/documents/${KEY}/v1/content.json`, { method: "POST" })).status, 405);
    assert.equal((await call(`/api/documents/${KEY}/v1/content.json`, { token: null })).status, 401);
    const versions = (await (await call(`/api/documents/${KEY}`)).json()).documents;
    assert.ok(!("files" in versions[0]) && !("cv_pdf_key" in versions[0]));
    assert.ok(!JSON.stringify(await (await call("/api/applications")).json()).includes("files"));
  });

  test("a pending version, or a missing sheet, is 404; the master never leaves without the contact sheet", async () => {
    pending();
    assert.equal((await call(`/api/documents/${KEY}/v1/content.json`)).status, 404);
    keep();
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    await runDocumentsScheduled(docEnv(), { fetch: globalThis.fetch, now: NOW });
    docs.store.delete("master/contact.json");
    assert.equal((await call(`/api/documents/${KEY}/v1/content.json`)).status, 404);
    assert.equal(row().status, "ready"); // the content stays, nothing is marked
  });

  test("a row left running for more than STUCK_MINUTES goes back to pending and is taken; a fresh one is left", async () => {
    keep();
    pending();
    const fresh = new Date(NOW.getTime() - 5 * 60_000).toISOString();
    const stale = new Date(NOW.getTime() - (STUCK_MINUTES + 1) * 60_000).toISOString();
    db.raw.prepare("UPDATE documents SET status = 'running', updated_at = ?").run(fresh);
    const api = anthropic([good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let r = await run();
    assert.deepEqual([r.outcome, r.counters.requeued, row().status], ["idle", 0, "running"]);
    db.raw.prepare("UPDATE documents SET updated_at = ?").run(stale);
    r = await run();
    assert.deepEqual([r.outcome, r.counters.requeued, r.counters.ready, row().status], ["ok", 1, 1, "ready"]);
  });

  test("an api_error row is retried once by the cron, never twice; a validator code never is", async () => {
    keep();
    pending();
    const api = anthropic([{ status: 500 }, { status: 500 }, good()]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let r = await run();
    assert.deepEqual([row().status, row().error_code, row().auto_retried], ["failed", "api_error", 0]);
    r = await run(); // the retry: pending again, taken, ready
    assert.deepEqual([r.counters.auto_retried, r.counters.ready, row().status, row().auto_retried], [1, 1, "ready", 1]);
    db.raw.prepare("UPDATE documents SET status = 'failed', error_code = 'api_error'").run();
    r = await run();
    assert.deepEqual([r.outcome, r.counters.auto_retried, row().status], ["idle", 0, "failed"]);
    db.raw.prepare("UPDATE documents SET error_code = 'headline_techs', auto_retried = 0").run();
    r = await run();
    assert.deepEqual([r.outcome, r.counters.auto_retried, row().status], ["idle", 0, "failed"]);
  });

  test("the Worker bundle imports no renderer, no PDF library and no font", () => {
    const src = new URL("../src/", import.meta.url);
    const seen = new Set();
    const queue = ["index.js"];
    while (queue.length) {
      const name = queue.shift();
      if (seen.has(name)) continue;
      seen.add(name);
      const text = readFileSync(new URL(name, src), "utf8");
      for (const lib of ["render.js", "fonts.js", "pdf-lib", "fflate", "fontkit", ".ttf"]) {
        assert.ok(!text.includes(lib), `${name} mentions ${lib}`);
      }
      for (const m of text.matchAll(/from "\.\/([a-z]+\.js)"/g)) queue.push(m[1]);
    }
    assert.ok(seen.has("documents.js") && seen.has("ai.js") && seen.has("inbox.js"));
    assert.ok(!existsSync(new URL("fonts.js", src)));
  });
});
