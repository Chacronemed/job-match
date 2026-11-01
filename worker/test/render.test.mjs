// ATS rendering (render.js, ADR 0017 part 3): the PDF is real text with the headings in order,
// the accents intact and the contact details present; the DOCX is a zip of well-formed OOXML
// with the same sections; the file names come from the contact sheet and the company.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { unzipSync } from "fflate";
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";

import {
  cvModel,
  emphasize,
  fileName,
  fmtDate,
  fmtMonth,
  HEADINGS,
  letterModel,
  MAX_PAGES,
  renderAll,
  renderCvDocx,
  renderCvPdf,
  renderCvPdfInfo,
  renderLetterPdf,
} from "../src/render.js";

const FONTS = {
  regular: readFileSync(new URL("../fonts/Inter-Regular.ttf", import.meta.url)),
  bold: readFileSync(new URL("../fonts/Inter-Bold.ttf", import.meta.url)),
};
const NOW = new Date("2026-11-01T08:10:00Z");

const MASTER = {
  headline: "Ingénieur DevOps",
  education: [{ degree: "Diplôme d’ingénieur — Data Science", school: "ENSIAS", location: "Rabat", start: "2022-09", end: "2025-06" }],
  languages: [{ name: "Français", level: "bilingue" }, { name: "Anglais", level: "courant" }],
  certifications: ["Responsive Web Design — freeCodeCamp"],
  skill_groups: [
    { group: "Conteneurs & IaC", items: ["Kubernetes (GKE)", "Docker", "Helm", "Terraform", "Ansible"] },
    { group: "CI/CD & Git", items: ["GitLab CI/CD", "Jenkins", "Git"] },
  ],
  extras: ["Ex-président de la branche étudiante IEEE : organisation de conférences."],
};
const CONTACT = {
  first_name: "Jean-Élie", last_name: "Trapmarker", title: "Ingénieur DevOps / Cloud", email: "jean.trap@example.com",
  phone: "+33 6 12 34 56 78", linkedin: "linkedin.com/in/trapjean", github: "github.com/trapjean", location: "Île-de-France, France",
};
const CONTENT = {
  job_key: "france_travail:AAA111", version: 1, language: "fr", availability: "Disponible immédiatement",
  offer: { key: "france_travail:AAA111", title: "Ingénieur DevOps Kubernetes", company: "Initech & Cœur" },
  profile: "Ingénieur DevOps orienté Kubernetes et GCP, à l’aise en production. Je cherche un CDI DevOps / Cloud. Disponible immédiatement.",
  selected_bullets: [],
  skill_groups: [
    { group: "CI/CD & Git", items: ["GitLab CI/CD", "Git"] },
    { group: "Conteneurs & IaC", items: ["Kubernetes (GKE)", "Terraform"] },
  ],
  headline_techs: ["Kubernetes", "Terraform", "GitLab CI/CD", "Helm", "Prometheus"],
  highlights: ["kubernetes", "terraform", "gke"],
  letter: {
    paragraphs: [
      { sentences: [{ text: "Votre offre chez Initech & Cœur m’intéresse.", sources: [] }, { text: "Elle réunit CI/CD et Kubernetes.", sources: [] }] },
      { sentences: [{ text: "Chez Acme Cloud, j’ai migré 12 services vers Kubernetes.", sources: ["exp1.b1"] }] },
      { sentences: [{ text: "Disponible immédiatement.", sources: [] }] },
    ],
  },
  cv: {
    experiences: [
      { id: "exp1", employer: "Acme Cloud", title: "Ingénieur DevOps (alternance)", start: "2025-10", end: "2026-10", location: "Nantes", bullets: [{ id: "exp1.b1", text: "Migration de 12 services vers Kubernetes (GKE) : 30 merge requests par mois, déploiements hebdomadaires." }] },
      { id: "exp2", employer: "Globex", title: "Stagiaire DevOps", start: "2024-05", end: "2024-07", location: "Lyon", bullets: [{ id: "exp2.b1", text: "Déploiement sur AWS avec Terraform, supervision Prometheus." }] },
    ],
    projects: [{ id: "proj1", name: "Smart Parking", bullets: [{ id: "proj1.b1", text: "IoT et Python, modèles ARIMA." }] }],
  },
};

async function pdfText(bytes) {
  const doc = await pdfjs.getDocument({ data: new Uint8Array(bytes), useSystemFonts: false, disableFontFace: true }).promise;
  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const tc = await page.getTextContent();
    pages.push(tc.items.map((it) => it.str).join(" "));
  }
  return { numPages: doc.numPages, text: pages.join("\n").replace(/\s+/g, " ") };
}

function inOrder(text, parts) {
  let at = -1;
  for (const p of parts) {
    const i = text.indexOf(p, at + 1);
    assert.ok(i > at, "missing or out of order: " + p);
    at = i;
  }
}

describe("models", () => {
  test("the CV model keeps the section order and the experiences as given (most recent first)", () => {
    const m = cvModel(CONTENT, MASTER, CONTACT);
    assert.deepEqual(m.sections.map((s) => s.key), ["profile", "experience", "skills", "education", "projects", "languages", "extras"]);
    assert.equal(m.name, "Jean-Élie Trapmarker");
    assert.equal(m.title, "Ingénieur DevOps / Cloud — Kubernetes, Terraform, GitLab CI/CD, Helm, Prometheus");
    assert.equal(m.sections[1].entries[0].title, "Ingénieur DevOps (alternance) — Acme Cloud");
    assert.equal(m.sections[1].entries[0].meta, "Nantes  |  oct. 2025 – oct. 2026");
    assert.deepEqual(m.sections[2].lines, [{ label: "CI/CD & Git", text: "GitLab CI/CD, Git" }, { label: "Conteneurs & IaC", text: "Kubernetes (GKE), Terraform" }]);
    assert.ok(m.contact.includes("jean.trap@example.com") && m.contact.includes("+33 6 12 34 56 78"));
  });

  test("the letter model adds the date, the salutation, the closing and the signature", () => {
    const m = letterModel(CONTENT, CONTACT, NOW);
    assert.equal(m.date, "Le 1er novembre 2026");
    assert.equal(m.salutation, "Madame, Monsieur,");
    assert.equal(m.subject, "Objet : candidature au poste de Ingénieur DevOps Kubernetes");
    assert.equal(m.paragraphs[0], "Votre offre chez Initech & Cœur m’intéresse. Elle réunit CI/CD et Kubernetes.");
    assert.equal(m.signature, "Jean-Élie Trapmarker");
    const en = letterModel({ ...CONTENT, language: "en" }, CONTACT, new Date("2026-03-04T00:00:00Z"));
    assert.deepEqual([en.date, en.salutation], ["4 March 2026", "Dear Hiring Team,"]);
    assert.equal(fmtDate("2026-11-21T10:00:00Z", "fr"), "Le 21 novembre 2026");
    assert.equal(fmtMonth(null, "en"), "present");
  });

  test("file names are ASCII, built from the contact and the company", () => {
    assert.equal(fileName("CV", CONTACT, "Initech & Cœur", "pdf"), "CV_Jean_Elie_Trapmarker_Initech_C_ur.pdf");
    assert.equal(fileName("Lettre", CONTACT, "", "docx"), "Lettre_Jean_Elie_Trapmarker.docx");
  });
});

describe("PDF", () => {
  test("the CV is one page of real text: headings in order, keywords, accents, contact", async () => {
    const bytes = await renderCvPdf(cvModel(CONTENT, MASTER, CONTACT), FONTS);
    const { numPages, text } = await pdfText(bytes);
    assert.equal(numPages, 1);
    inOrder(text, ["Jean-Élie Trapmarker", "Kubernetes, Terraform, GitLab CI/CD", "PROFIL", "EXPÉRIENCE", "Acme Cloud", "Globex", "COMPÉTENCES", "CI/CD & Git : GitLab CI/CD, Git", "FORMATION", "PROJETS", "LANGUES", "ENGAGEMENT"]);
    assert.ok(!text.includes("CERTIFICATIONS") && !text.includes("freeCodeCamp"), "certifications are not rendered");
    // Bold runs come back as separate text items: "Kubernetes" and "GKE" rather than "Kubernetes (GKE)".
    for (const kw of ["Kubernetes", "GKE", "Terraform", "30 merge requests", "jean.trap@example.com", "+33 6 12 34 56 78", "Île-de-France", "Disponible immédiatement", "déploiements", "à l’aise", "Diplôme d’ingénieur"]) {
      assert.ok(text.includes(kw), "missing: " + kw);
    }
    assert.equal(new TextDecoder().decode(bytes.slice(0, 5)), "%PDF-");
  });

  test("English headings when the content is in English", async () => {
    const bytes = await renderCvPdf(cvModel({ ...CONTENT, language: "en" }, MASTER, CONTACT), FONTS);
    const { text } = await pdfText(bytes);
    inOrder(text, ["PROFILE", "EXPERIENCE", "Oct 2025 – Oct 2026", "SKILLS", "EDUCATION", "INVOLVEMENT"]);
    assert.deepEqual(Object.keys(HEADINGS.en), Object.keys(HEADINGS.fr));
  });

  test("bold runs: the offer's terms and the key numbers, by the template", async () => {
    assert.deepEqual(emphasize("Migration de 12 services vers Kubernetes (GKE), 30 merge requests par mois.", ["kubernetes", "gke"]), [
      { text: "Migration de ", bold: false }, { text: "12 services", bold: true }, { text: " vers ", bold: false },
      { text: "Kubernetes", bold: true }, { text: " (", bold: false }, { text: "GKE", bold: true }, { text: "), ", bold: false },
      { text: "30 merge requests", bold: true }, { text: " par mois.", bold: false },
    ]);
    assert.deepEqual(emphasize("coût réduit de 80 % ; 15+ applications", []), [
      { text: "coût réduit de ", bold: false }, { text: "80 %", bold: true }, { text: " ; ", bold: false }, { text: "15+", bold: true }, { text: " applications", bold: false },
    ]);
    // Bare numbers inside names stay regular.
    assert.deepEqual(emphasize("RHEL 5 à 9, Route 53, S3, EC2, Top 10, 7 pays", []), [
      { text: "RHEL 5 à 9, Route 53, S3, EC2, Top 10, ", bold: false }, { text: "7 pays", bold: true },
    ]);
    const xml = new TextDecoder().decode(unzipSync(renderCvDocx(cvModel(CONTENT, MASTER, CONTACT)))["word/document.xml"]);
    assert.ok(xml.includes("<w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">Kubernetes</w:t>"), "bold run in the DOCX");
  });

  test("a realistic CV fills one page at 90 % or more; an oversized one is cut at one page", async () => {
    const dense = JSON.parse(JSON.stringify(CONTENT));
    dense.cv.experiences[0].bullets = Array.from({ length: 5 }, (_, k) => ({ id: "e1b" + k, text: "Maintien en conditions opérationnelles de 15+ applications critiques : mises en production hebdomadaires sur 12 mois, supervision et suivi de la disponibilité " + k + "." }));
    dense.cv.experiences[1].bullets = Array.from({ length: 5 }, (_, k) => ({ id: "e2b" + k, text: "Conteneurisation et orchestration de microservices sur Kubernetes (GKE) : packaging Helm multi-environnements, Ingress, RBAC, IAM ; pipelines complets build, tests, production " + k + "." }));
    dense.cv.experiences.push({ id: "exp3", employer: "AIKINI", title: "Stagiaire DevOps", start: "2023-05", end: "2023-07", location: "Marrakech", bullets: [{ id: "e3b1", text: "Conteneurisation Docker, pipeline CI/CD, supervision Prometheus et Grafana, logs via ELK ; déploiement web sur AWS (EC2, ELB, ACM, Route 53, S3)." }] });
    dense.cv.projects = Array.from({ length: 4 }, (_, k) => ({ id: "p" + k, name: "Projet " + k, bullets: [{ id: "p" + k + "b", text: "Application web sur des instances EC2 derrière un Load Balancer sécurisé via ACM, avec un groupe d'auto-scaling ; DNS privé Route 53 et artefacts dans S3." }] }));
    dense.skill_groups = MASTER.skill_groups;
    const info = await renderCvPdfInfo(cvModel(dense, MASTER, CONTACT), FONTS);
    const { numPages } = await pdfText(info.bytes);
    assert.equal(numPages, 1);
    assert.equal(info.pages, 1);
    assert.ok(info.fill >= 0.9 && info.fill <= 1, "fill: " + info.fill);
    assert.ok(info.size >= 9.5 && info.size <= 10.5, "size: " + info.size);

    const long = JSON.parse(JSON.stringify(dense));
    for (let i = 0; i < 8; i++) {
      long.cv.experiences.push({ id: "x" + i, employer: "Employeur " + i, title: "Poste " + i, start: "2020-01", end: "2020-06", location: "Paris",
        bullets: Array.from({ length: 6 }, (_, k) => ({ id: "x" + i + ".b" + k, text: "Réalisation " + k + " : " + "mot ".repeat(30) })) });
    }
    const cut = await renderCvPdfInfo(cvModel(long, MASTER, CONTACT), FONTS);
    const out = await pdfText(cut.bytes);
    assert.equal(out.numPages, 1);
    assert.ok(cut.fill >= 0.9, "fill: " + cut.fill);
    assert.ok(cut.cut === true && cut.compact === true, "the last resort is marked");
    assert.ok(!out.text.includes("PROJETS"), "projects dropped first");
  });

  test("the letter carries the template's formulas and the model's paragraphs", async () => {
    const bytes = await renderLetterPdf(letterModel(CONTENT, CONTACT, NOW), FONTS);
    const { numPages, text } = await pdfText(bytes);
    assert.equal(numPages, 1);
    inOrder(text, ["Jean-Élie Trapmarker", "Le 1er novembre 2026", "Initech & Cœur", "Objet", "Madame, Monsieur,", "j’ai migré 12 services", "Disponible immédiatement", "salutations distinguées", "Jean-Élie Trapmarker"]);
  });
});

describe("DOCX", () => {
  test("a zip of well-formed OOXML with the headings in order and escaped text", () => {
    const bytes = renderCvDocx(cvModel(CONTENT, MASTER, CONTACT));
    const files = unzipSync(bytes);
    assert.deepEqual(Object.keys(files).sort(), ["[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels", "word/document.xml", "word/styles.xml"]);
    const xml = new TextDecoder().decode(files["word/document.xml"]);
    inOrder(xml, ["Jean-Élie Trapmarker", ">Profil<", ">Expérience<", "Acme Cloud", ">Compétences<", "CI/CD &amp; Git : ", ">Formation<", ">Projets<", ">Langues<", ">Engagement<"]);
    assert.ok(!xml.includes("Certifications"));
    assert.ok(xml.includes("Initech &amp; Cœur") || !xml.includes("Initech &"), "ampersands are escaped");
    assert.ok(xml.includes('w:val="Heading1"'));
    assert.ok(!xml.includes("<w:tbl>") && !xml.includes("<w:drawing>"), "no table, no drawing");
    assert.equal(bytes[0], 0x50); // "PK"
  });
});

describe("renderAll", () => {
  test("four files, the right types and names", async () => {
    const files = await renderAll(CONTENT, MASTER, CONTACT, FONTS, NOW);
    assert.deepEqual(files.map((f) => [f.name, f.filename]), [
      ["cv.pdf", "CV_Jean_Elie_Trapmarker_Initech_C_ur.pdf"],
      ["cv.docx", "CV_Jean_Elie_Trapmarker_Initech_C_ur.docx"],
      ["letter.pdf", "Lettre_Jean_Elie_Trapmarker_Initech_C_ur.pdf"],
      ["letter.docx", "Lettre_Jean_Elie_Trapmarker_Initech_C_ur.docx"],
    ]);
    assert.equal(files[0].contentType, "application/pdf");
    assert.ok(files[1].contentType.endsWith("wordprocessingml.document"));
    for (const f of files) assert.ok(f.bytes.length > 1000, f.name);
  });
});
