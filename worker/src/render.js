// ATS rendering of the application documents (ADR 0017, part 3): the CV and the cover letter
// as PDF (pdf-lib, Inter embedded so accents are real text) and as DOCX (hand-written OOXML
// zipped with fflate). One column, standard headings in a fixed order, no image, no icon, no
// table. Bold is the template's: the terms the offer names (content.highlights) and the key
// numbers, never the model's. The CV is laid out to fill one page (90 % or more, never two):
// the projects and the Engagement line are the levers, then the type size. Pure: everything
// comes in as values and goes out as bytes. The contact details appear here and nowhere upstream.

import fontkit from "@pdf-lib/fontkit";
import { strToU8, zipSync } from "fflate";
import { PDFDocument, rgb } from "pdf-lib";

export const HEADINGS = {
  fr: { profile: "Profil", experience: "Expérience", skills: "Compétences", education: "Formation", projects: "Projets", languages: "Langues", extras: "Engagement" },
  en: { profile: "Profile", experience: "Experience", skills: "Skills", education: "Education", projects: "Projects", languages: "Languages", extras: "Involvement" },
};
// Certifications stay in the master but are not rendered (the page is for the experience).
export const SECTION_ORDER = ["profile", "experience", "skills", "education", "projects", "languages", "extras"];
const MONTHS = {
  fr: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};
const MONTHS_LONG = {
  fr: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};
const PAGE = { width: 595.28, height: 841.89 }; // A4, points
const MARGIN = 46; // 16 mm, close to the original CV
export const MAX_PAGES = 1;
export const MIN_FILL = 0.9;
export const SIZES = [10.5, 10, 9.5];

export function fmtMonth(ym, language) {
  const m = /^(\d{4})-(\d{2})/.exec(String(ym || ""));
  if (!m) return language === "en" ? "present" : "aujourd’hui";
  return MONTHS[language === "en" ? "en" : "fr"][Number(m[2]) - 1] + " " + m[1];
}

export function fmtDate(date, language) {
  const d = date instanceof Date ? date : new Date(date);
  const months = MONTHS_LONG[language === "en" ? "en" : "fr"];
  const day = d.getUTCDate();
  return language === "en"
    ? day + " " + months[d.getUTCMonth()] + " " + d.getUTCFullYear()
    : "Le " + (day === 1 ? "1er" : day) + " " + months[d.getUTCMonth()] + " " + d.getUTCFullYear();
}

function lang(content) {
  return content && content.language === "en" ? "en" : "fr";
}

function fullName(contact) {
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ");
}

function contactLine(contact) {
  return [contact.location, contact.email, contact.phone, contact.linkedin, contact.github].filter(Boolean).join("  •  ");
}

function fold(text) {
  return String(text).normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

// ---------------------------------------------------------------- emphasis

// Key numbers only: a figure with a sign or a unit (15+, 80 %, 30 merge requests, 7 pays), never
// a bare number inside a name (EC2, S3, RHEL 5 à 9, Top 10).
const NUMBER_RUN = /(?<![\p{L}\p{N}])\d+(?:[.,]\d+)?(?:\s?(?:\+|%|€)|\s?k(?![\p{L}])|\s(?:merge requests?|MR|ans?|mois|pays|serveurs?|applications?|services?|clusters?|countries|servers?|months?|years?))(?![\p{L}\p{N}])/gu;

function escapeRe(t) {
  return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// The text as runs {text, bold}: whole-term matches of the highlights, and the key numbers.
export function emphasize(text, highlights = []) {
  const src = String(text);
  const marks = new Array(src.length).fill(false);
  const folded = fold(src);
  const mark = (re, hay) => {
    for (const m of hay.matchAll(re)) {
      for (let i = m.index; i < m.index + m[0].length && i < marks.length; i++) marks[i] = true;
    }
  };
  for (const h of highlights) {
    const f = fold(h).trim();
    if (f.length < 3) continue;
    mark(new RegExp("(?<![\\p{L}\\p{N}])" + escapeRe(f) + "(?![\\p{L}\\p{N}])", "giu"), folded);
  }
  mark(NUMBER_RUN, src);
  const runs = [];
  let cur = null;
  for (let i = 0; i < src.length; i++) {
    if (cur && cur.bold === marks[i]) cur.text += src[i];
    else {
      cur = { text: src[i], bold: marks[i] };
      runs.push(cur);
    }
  }
  return runs.length ? runs : [{ text: src, bold: false }];
}

// ---------------------------------------------------------------- models

// The CV as plain sections, the same for the PDF and the DOCX.
export function cvModel(content, master, contact) {
  const l = lang(content);
  const h = HEADINGS[l];
  const cv = content.cv || { experiences: [], projects: [] };
  const highlights = Array.isArray(content.highlights) ? content.highlights : [];
  const sections = [];
  sections.push({ key: "profile", heading: h.profile, paragraphs: [content.profile || ""] });
  sections.push({
    key: "experience",
    heading: h.experience,
    entries: cv.experiences.map((e) => ({
      title: [e.title, e.employer].filter(Boolean).join(" — "),
      meta: [e.location, fmtMonth(e.start, l) + " – " + fmtMonth(e.end, l)].filter(Boolean).join("  |  "),
      bullets: e.bullets.map((b) => b.text),
    })),
  });
  // The display groups: the model's choice, else the master's groups (older content).
  let groups = Array.isArray(content.skill_groups) && content.skill_groups.length ? content.skill_groups : master.skill_groups || [];
  groups = groups.filter((g) => g && typeof g.group === "string" && Array.isArray(g.items) && g.items.length);
  sections.push({ key: "skills", heading: h.skills, lines: groups.map((g) => ({ label: g.group, text: g.items.join(", ") })) });
  sections.push({
    key: "education",
    heading: h.education,
    entries: (master.education || []).map((ed) => ({
      title: ed.degree,
      meta: [ed.school, ed.location, fmtMonth(ed.start, l) + " – " + fmtMonth(ed.end, l)].filter(Boolean).join("  |  "),
      bullets: [],
    })),
  });
  sections.push({ key: "projects", heading: h.projects, entries: (cv.projects || []).map((p) => ({ title: p.name, meta: "", bullets: p.bullets.map((b) => b.text) })) });
  sections.push({ key: "languages", heading: h.languages, paragraphs: [(master.languages || []).map((x) => x.name + " : " + x.level).join("  •  ")] });
  sections.push({ key: "extras", heading: h.extras, paragraphs: (master.extras || []).length ? [master.extras.join(" ")] : [] });
  const techs = Array.isArray(content.headline_techs) ? content.headline_techs.filter((t) => typeof t === "string" && t.trim()) : [];
  const baseTitle = contact.title || master.headline || "";
  return {
    language: l,
    name: fullName(contact),
    title: techs.length ? baseTitle + " — " + techs.join(", ") : baseTitle,
    contact: contactLine(contact),
    highlights,
    sections: sections.filter((s) => (s.paragraphs && s.paragraphs.some((p) => p)) || (s.entries && s.entries.length) || (s.lines && s.lines.length)),
  };
}

// The letter as plain lines: the template adds the date, the salutation, the closing and the
// signature; the model only wrote the paragraphs.
export function letterModel(content, contact, now) {
  const l = lang(content);
  const paragraphs = ((content.letter && content.letter.paragraphs) || []).map((p) =>
    (p.sentences || []).map((s) => String(s.text || "").trim()).filter(Boolean).join(" "),
  );
  const company = (content.offer && content.offer.company) || "";
  const title = (content.offer && content.offer.title) || "";
  return {
    language: l,
    name: fullName(contact),
    contactLines: [contact.title, contact.location, contact.email, contact.phone, contact.linkedin].filter(Boolean),
    date: fmtDate(now, l),
    recipient: company,
    subject: l === "en" ? "Subject: application for the " + title + " position" : "Objet : candidature au poste de " + title,
    salutation: l === "en" ? "Dear Hiring Team," : "Madame, Monsieur,",
    paragraphs,
    closing: l === "en"
      ? "I would welcome the opportunity to discuss my application with you. Yours sincerely,"
      : "Je vous prie d’agréer, Madame, Monsieur, l’expression de mes salutations distinguées.",
    signature: fullName(contact),
  };
}

// A file name without accents or spaces: CV_Prenom_Nom_Entreprise.pdf.
export function fileName(kind, contact, company, ext) {
  const clean = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const parts = [kind, clean(contact.first_name), clean(contact.last_name), clean(company)].filter(Boolean);
  return parts.join("_") + "." + ext;
}

// ---------------------------------------------------------------- PDF

// Words of mixed runs wrapped to a width: each line is a list of {text, bold} pieces.
function wrapRuns(runs, fonts, size, maxWidth) {
  const words = [];
  for (const r of runs) {
    const parts = r.text.split(/(\s+)/);
    for (const p of parts) if (p) words.push({ text: p, bold: r.bold, space: /^\s+$/.test(p) });
  }
  const width = (w) => (w.bold ? fonts.bold : fonts.regular).widthOfTextAtSize(w.text, size);
  const lines = [];
  let line = [];
  let lineWidth = 0;
  for (const w of words) {
    if (w.text.includes("\n")) {
      lines.push(line);
      line = [];
      lineWidth = 0;
      continue;
    }
    const ww = width(w);
    if (lineWidth + ww > maxWidth && line.length && !w.space) {
      while (line.length && line[line.length - 1].space) line.pop();
      lines.push(line);
      line = [];
      lineWidth = 0;
    }
    if (w.space && !line.length) continue;
    line.push(w);
    lineWidth += ww;
  }
  if (line.length) lines.push(line);
  return lines.length ? lines : [[]];
}

class Writer {
  constructor(doc, fonts, size, maxPages = Infinity) {
    this.doc = doc;
    this.fonts = fonts;
    this.size = size;
    this.page = null;
    this.y = 0;
    this.pages = 0;
    this.maxPages = maxPages;
    this.overflow = false;
    this.width = PAGE.width - 2 * MARGIN;
    this.firstPageUsed = 0;
    this.lineHeight = 1.3; // 1.22 in the compact variant
    this.newPage();
  }
  newPage() {
    this.page = this.doc.addPage([PAGE.width, PAGE.height]);
    this.pages += 1;
    this.y = PAGE.height - MARGIN;
  }
  ensure(height) {
    if (this.y - height >= MARGIN) return true;
    if (this.pages >= this.maxPages) {
      this.overflow = true;
      return false;
    }
    this.firstPageUsed = this.pages === 1 ? this.fill() : this.firstPageUsed;
    this.newPage();
    return true;
  }
  // How much of the page's writable height is used (page 1 when there are several).
  fill() {
    const top = PAGE.height - MARGIN;
    if (this.pages > 1) return this.firstPageUsed || 1;
    return (top - this.y) / (top - MARGIN);
  }
  runs(runs, { size = this.size, indent = 0, color = rgb(0.1, 0.1, 0.1), gap = 0, lineHeight = this.lineHeight, bullet = false } = {}) {
    const lines = wrapRuns(runs, this.fonts, size, this.width - indent - (bullet ? 12 : 0));
    const lh = size * lineHeight;
    for (const [i, line] of lines.entries()) {
      if (!this.ensure(lh)) return;
      this.y -= lh;
      let x = MARGIN + indent + (bullet ? 12 : 0);
      if (bullet && i === 0) this.page.drawText("•", { x: MARGIN + indent + 2, y: this.y, size, font: this.fonts.regular, color });
      for (const w of line) {
        const font = w.bold ? this.fonts.bold : this.fonts.regular;
        this.page.drawText(w.text, { x, y: this.y, size, font, color });
        x += font.widthOfTextAtSize(w.text, size);
      }
    }
    this.y -= gap;
  }
  text(text, opts = {}) {
    const bold = Boolean(opts.bold);
    this.runs([{ text: String(text), bold }], opts);
  }
  heading(text) {
    const size = this.size + 1.5;
    if (!this.ensure(size * 3)) return;
    this.y -= size * 1.5;
    this.page.drawText(text.toUpperCase(), { x: MARGIN, y: this.y, size, font: this.fonts.bold, color: rgb(0.12, 0.2, 0.35) });
    this.y -= 4;
    this.page.drawLine({ start: { x: MARGIN, y: this.y }, end: { x: PAGE.width - MARGIN, y: this.y }, thickness: 0.6, color: rgb(0.12, 0.2, 0.35) });
    this.y -= 5;
  }
  space(n) {
    this.y -= n;
  }
}

async function newDoc(fontBytes, meta) {
  const doc = await PDFDocument.create();
  doc.registerFontkit(fontkit);
  const fonts = {
    regular: await doc.embedFont(fontBytes.regular, { subset: true }),
    bold: await doc.embedFont(fontBytes.bold, { subset: true }),
  };
  doc.setTitle(meta.title);
  doc.setAuthor(meta.author);
  doc.setProducer("job-match");
  doc.setCreator("job-match");
  return { doc, fonts };
}

// One layout: `variant` = {projects: how many project entries, extras: boolean}.
async function layoutCv(model, fontBytes, size, variant, maxPages = Infinity) {
  const { doc, fonts } = await newDoc(fontBytes, { title: "CV " + model.name, author: model.name });
  const w = new Writer(doc, fonts, size, maxPages);
  if (variant.compact) w.lineHeight = 1.22;
  const grey = rgb(0.3, 0.3, 0.3);
  w.text(model.name, { size: size + 7, bold: true, gap: 1 });
  if (model.title) w.text(model.title, { size: size + 0.5, gap: 1 });
  if (model.contact) w.text(model.contact, { size: size - 1, color: grey });
  for (const section of model.sections) {
    if (section.key === "extras" && !variant.extras) continue;
    let entries = section.entries || [];
    if (section.key === "projects") {
      entries = entries.slice(0, variant.projects);
      if (!entries.length) continue;
    }
    w.heading(section.heading);
    for (const p of section.paragraphs || []) w.runs(emphasize(p, model.highlights), { gap: 2 });
    for (const line of section.lines || []) {
      w.runs([{ text: line.label + " : ", bold: true }, ...emphasize(line.text, model.highlights)], { gap: 1 });
    }
    for (const e of entries) {
      w.text(e.title, { bold: true });
      if (e.meta) w.text(e.meta, { size: size - 1, color: grey });
      for (const b of e.bullets) w.runs(emphasize(b, model.highlights), { bullet: true });
      w.space(variant.compact ? 2 : 3);
    }
  }
  return { bytes: await doc.save(), pages: w.pages, fill: Math.min(1, w.fill()), size, projects: variant.projects, extras: variant.extras, compact: Boolean(variant.compact), cut: w.overflow };
}

// The fullest one-page layout: every variant (all the projects down to none, with and
// without the Engagement line) at each size, then the same with tighter lines; the first
// with 90 % or more of the page wins, else the best one-page fill, else the page is cut at
// the bottom (9.5 pt, compact, no projects) and `cut` says so.
export async function renderCvPdfInfo(model, fontBytes) {
  const projectsSection = model.sections.find((s) => s.key === "projects");
  const nProjects = projectsSection ? projectsSection.entries.length : 0;
  const hasExtras = model.sections.some((s) => s.key === "extras");
  const variants = [];
  for (const compact of [false, true]) {
    for (let p = nProjects; p >= 0; p--) {
      variants.push({ projects: p, extras: hasExtras, compact });
      if (hasExtras) variants.push({ projects: p, extras: false, compact });
    }
  }
  let best = null;
  for (const variant of variants) {
    for (const size of SIZES) {
      const out = await layoutCv(model, fontBytes, size, variant);
      if (out.pages === 1 && out.fill >= MIN_FILL) return out;
      if (out.pages === 1 && (!best || out.fill > best.fill)) best = out;
    }
  }
  if (best) return best;
  return layoutCv(model, fontBytes, SIZES[SIZES.length - 1], { projects: 0, extras: false, compact: true }, MAX_PAGES);
}

export async function renderCvPdf(model, fontBytes) {
  return (await renderCvPdfInfo(model, fontBytes)).bytes;
}

export async function renderLetterPdf(model, fontBytes) {
  const { doc, fonts } = await newDoc(fontBytes, { title: (model.language === "en" ? "Cover letter " : "Lettre de motivation ") + model.name, author: model.name });
  const w = new Writer(doc, fonts, 10.5);
  w.text(model.name, { size: 13, bold: true });
  for (const line of model.contactLines) w.text(line, { size: 9.5, color: rgb(0.3, 0.3, 0.3) });
  w.space(14);
  w.text(model.date);
  w.space(10);
  if (model.recipient) w.text(model.recipient, { bold: true });
  w.text(model.subject, { gap: 10 });
  w.text(model.salutation, { gap: 8 });
  for (const p of model.paragraphs) w.text(p, { gap: 8, lineHeight: 1.4 });
  w.text(model.closing, { gap: 18 });
  w.text(model.signature, { bold: true });
  return doc.save();
}

// ---------------------------------------------------------------- DOCX

function esc(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function run(text, { bold = false, size, color } = {}) {
  const rpr = [bold ? "<w:b/>" : "", size ? '<w:sz w:val="' + size * 2 + '"/>' : "", color ? '<w:color w:val="' + color + '"/>' : ""].join("");
  return "<w:r>" + (rpr ? "<w:rPr>" + rpr + "</w:rPr>" : "") + '<w:t xml:space="preserve">' + esc(text) + "</w:t></w:r>";
}

function para(text, { style, bold = false, size, color } = {}) {
  const ppr = style ? '<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' : "";
  return "<w:p>" + ppr + run(text, { bold, size, color }) + "</w:p>";
}

function paraRuns(runs, { style } = {}) {
  const ppr = style ? '<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' : "";
  return "<w:p>" + ppr + runs.map((r) => run(r.text, { bold: r.bold })).join("") + "</w:p>";
}

const DOCX_STYLES =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
  '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="20"/><w:lang w:val="fr-FR"/></w:rPr></w:rPrDefault>' +
  '<w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>' +
  '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>' +
  '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="40"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:caps/><w:color w:val="1F3359"/><w:sz w:val="23"/></w:rPr></w:style>' +
  '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="100" w:after="10"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>' +
  '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360" w:hanging="200"/><w:spacing w:after="30"/></w:pPr></w:style>' +
  "</w:styles>";

function docx(bodyXml, language) {
  const document =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
    bodyXml +
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="900" w:right="900" w:bottom="900" w:left="900" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>' +
    "</w:body></w:document>";
  const files = {
    "[Content_Types].xml": strToU8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
        "</Types>",
    ),
    "_rels/.rels": strToU8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        "</Relationships>",
    ),
    "word/document.xml": strToU8(document),
    "word/styles.xml": strToU8(DOCX_STYLES.replace('w:val="fr-FR"', 'w:val="' + (language === "en" ? "en-GB" : "fr-FR") + '"')),
    "word/_rels/document.xml.rels": strToU8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        "</Relationships>",
    ),
  };
  return zipSync(files, { level: 6 });
}

export function renderCvDocx(model) {
  let body = para(model.name, { style: "Title" });
  if (model.title) body += para(model.title, { bold: true });
  if (model.contact) body += para(model.contact, { size: 9, color: "555555" });
  for (const section of model.sections) {
    body += para(section.heading, { style: "Heading1" });
    for (const p of section.paragraphs || []) body += paraRuns(emphasize(p, model.highlights));
    for (const line of section.lines || []) body += paraRuns([{ text: line.label + " : ", bold: true }, ...emphasize(line.text, model.highlights)]);
    for (const e of section.entries || []) {
      body += para(e.title, { style: "Heading2" });
      if (e.meta) body += para(e.meta, { size: 9, color: "555555" });
      for (const b of e.bullets) body += paraRuns([{ text: "• ", bold: false }, ...emphasize(b, model.highlights)], { style: "ListBullet" });
    }
  }
  return docx(body, model.language);
}

export function renderLetterDocx(model) {
  let body = para(model.name, { bold: true, size: 13 });
  for (const line of model.contactLines) body += para(line, { size: 9.5, color: "555555" });
  body += para("");
  body += para(model.date);
  body += para("");
  if (model.recipient) body += para(model.recipient, { bold: true });
  body += para(model.subject);
  body += para("");
  body += para(model.salutation);
  for (const p of model.paragraphs) body += para(p);
  body += para("");
  body += para(model.closing);
  body += para("");
  body += para(model.signature, { bold: true });
  return docx(body, model.language);
}

export const MIME = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

// The four files of one version, as {name, bytes, contentType, filename}.
export async function renderAll(content, master, contact, fontBytes, now) {
  const cv = cvModel(content, master, contact);
  const letter = letterModel(content, contact, now);
  const company = (content.offer && content.offer.company) || "";
  return [
    { name: "cv.pdf", bytes: await renderCvPdf(cv, fontBytes), contentType: MIME.pdf, filename: fileName("CV", contact, company, "pdf") },
    { name: "cv.docx", bytes: renderCvDocx(cv), contentType: MIME.docx, filename: fileName("CV", contact, company, "docx") },
    { name: "letter.pdf", bytes: await renderLetterPdf(letter, fontBytes), contentType: MIME.pdf, filename: fileName(cv.language === "en" ? "Cover_letter" : "Lettre", contact, company, "pdf") },
    { name: "letter.docx", bytes: renderLetterDocx(letter), contentType: MIME.docx, filename: fileName(cv.language === "en" ? "Cover_letter" : "Lettre", contact, company, "docx") },
  ];
}
