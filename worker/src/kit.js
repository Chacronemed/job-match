// The answer kit of one offer (ADR 0023): what an application form asks besides the CV and
// the letter. Pure, no import: the Worker (documents.js) uses availabilityText, the
// dashboard's offer page and the local `job-match apply` (scripts/apply-render.mjs) build the
// same kit with answerKit. Nothing here is written by the model except `content.answers`,
// which the documents validator has already checked against the master. The salary never
// comes from the model: from private/apply.yaml (`remuneration`) only, and with
// `mode: manuel` there is no salary value at all, only the zone's benchmark to read.

const MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export const SALARY_MODES = ["manuel", "fourchette"];

function isoDay(date) {
  return (date instanceof Date ? date : new Date(date)).toISOString().slice(0, 10);
}

// "Disponible immédiatement" once available_from is past, else the month and the year.
export function availabilityText(availableFrom, today, language) {
  const from = String(availableFrom || "").slice(0, 10);
  const now = isoDay(today);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || from <= now) {
    return language === "en" ? "Available immediately" : "Disponible immédiatement";
  }
  const month = Number(from.slice(5, 7)) - 1;
  const year = from.slice(0, 4);
  return language === "en" ? "Available from " + MONTHS_EN[month] + " " + year : "Disponible à partir de " + MONTHS_FR[month] + " " + year;
}

// Accent-folded, lowercased, single spaces: how a location meets a zone's words.
export function foldText(text) {
  return String(text || "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// The benchmark of the offer's zone: the first `reperes` entry one of whose `match` words is
// in the location, else the first entry without words (the default), else null.
export function salaryBenchmark(remuneration, location) {
  const list = remuneration && Array.isArray(remuneration.reperes) ? remuneration.reperes : [];
  const where = " " + foldText(location) + " ";
  for (const r of list) {
    const words = Array.isArray(r.match) ? r.match.map(foldText).filter(Boolean) : [];
    if (words.some((w) => where.includes(" " + w + " "))) return { zone: String(r.zone || ""), text: String(r.texte || "") };
  }
  const fallback = list.find((r) => !Array.isArray(r.match) || r.match.length === 0);
  return fallback ? { zone: String(fallback.zone || ""), text: String(fallback.texte || "") } : null;
}

const GROUPED = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

// The range as one line: "40 000 – 46 000 € brut annuel". Narrow spaces become plain ones, so
// the copied text is the same everywhere.
export function salaryRangeText(range) {
  const n = (v) => GROUPED.format(v).replace(/[  ]/g, " ");
  const tail = [range.devise || "€", range.periode || ""].filter(Boolean).join(" ");
  return n(range.min) + " – " + n(range.max) + " " + tail;
}

// The salary item: never a value in `manuel`, the range in `fourchette`, and the benchmark of
// the zone in both (the form filler shows it next to the field it leaves empty).
export function salaryItem(apply, location) {
  const rem = apply && apply.remuneration ? apply.remuneration : null;
  const mode = rem && SALARY_MODES.includes(rem.mode) ? rem.mode : "manuel";
  const benchmark = salaryBenchmark(rem, location);
  const base = { key: "salary", label: "Prétentions salariales", mode, benchmark, copy: false, text: null };
  if (mode === "fourchette" && rem.fourchette && Number.isFinite(rem.fourchette.min) && Number.isFinite(rem.fourchette.max)) {
    return { ...base, text: salaryRangeText(rem.fourchette), copy: true, range: { min: rem.fourchette.min, max: rem.fourchette.max } };
  }
  const note = benchmark ? "Repère " + (benchmark.zone || "de la zone") + " : " + benchmark.text : "Aucun repère pour cette zone dans private/apply.yaml";
  return { ...base, mode: "manuel", note: "À remplir à la main. " + note };
}

// One answer of the model: its sentences joined, "" when the version has none (older content).
export function answerText(content, name) {
  const a = content && content.answers && content.answers[name];
  if (!a || !Array.isArray(a.sentences)) return "";
  return a.sentences.map((s) => String((s && s.text) || "").trim()).filter(Boolean).join(" ");
}

// The kit, in the order a form usually asks. Each item: {key, label, text, copy} and, for a
// fixed answer, the `match` words its question is recognized by. `text` null = nothing to
// paste (missing in apply.yaml, or the salary in `manuel`), with a `note` saying why.
export function answerKit(content, master, apply, now, location) {
  const language = content && content.language === "en" ? "en" : "fr";
  const cfg = apply && typeof apply === "object" ? apply : {};
  const item = (key, label, text, extra = {}) => {
    const t = typeof text === "string" && text.trim() ? text.trim() : null;
    return { key, label, text: t, copy: t !== null, ...extra };
  };
  const missing = { note: "Absent : regénère les documents (prompt v6 et plus)." };
  const motivation = answerText(content, "motivation");
  const why = answerText(content, "why_company");
  const items = [
    item("motivation", "Motivation (courte)", motivation, motivation ? {} : missing),
    item("why_company", "Pourquoi cette entreprise", why, why ? {} : missing),
    item("availability", "Disponibilité", availabilityText(master && master.available_from, now, language)),
    item("mobility", "Mobilité", cfg.mobilite || (master && master.mobility) || "", { note: "Absente du maître et de private/apply.yaml." }),
    item("notice", "Préavis", cfg.preavis || "", { note: "Absent de private/apply.yaml (preavis)." }),
    salaryItem(cfg, location),
  ];
  for (const f of Array.isArray(cfg.reponses_fixes) ? cfg.reponses_fixes : []) {
    if (!f || typeof f.label !== "string") continue;
    items.push(item("fixed", f.label, f.reponse, { match: Array.isArray(f.match) ? f.match.slice() : [] }));
  }
  for (const it of items) if (it.text !== null) delete it.note;
  return items;
}
