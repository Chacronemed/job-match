#!/usr/bin/env node
// Local rendering for `job-match apply` (ADR 0023): the same render.js the dashboard ships,
// the same Inter fonts, and the same answer kit (kit.js) as the offer page.
//
//   node scripts/apply-render.mjs <bundle.json> <out-dir> [--location TEXT] [--now ISO]
//
// bundle.json: {content, master, contact, apply} (apply may be null), as the Worker serves
// it. Writes the CV PDF and the letter PDF under their template names, and kit.json
// ({items, letter_text}). Prints {cv, letter, kit} (paths) as JSON on stdout, nothing else:
// no text of a document ever reaches the terminal.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { answerKit } from "../worker/src/kit.js";
import { cvModel, fileName, letterModel, renderCvPdf, renderLetterPdf } from "../worker/src/render.js";

const args = process.argv.slice(2);
const option = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const [bundlePath, outDir] = args.filter((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--")));
if (!bundlePath || !outDir) {
  console.error("usage: apply-render.mjs <bundle.json> <out-dir> [--location TEXT] [--now ISO]");
  process.exit(2);
}
const now = option("--now") ? new Date(option("--now")) : new Date();
const { content, master, contact, apply } = JSON.parse(readFileSync(bundlePath, "utf8"));
const location = option("--location") ?? (content.offer && content.offer.location) ?? "";
const fonts = {
  regular: readFileSync(new URL("../worker/fonts/Inter-Regular-latin.ttf", import.meta.url)),
  bold: readFileSync(new URL("../worker/fonts/Inter-Bold-latin.ttf", import.meta.url)),
};

mkdirSync(outDir, { recursive: true });
const company = (content.offer && content.offer.company) || "";
const cv = cvModel(content, master, contact);
const letter = letterModel(content, contact, now);
const cvPath = join(outDir, fileName("CV", contact, company, "pdf"));
const letterPath = join(outDir, fileName(cv.language === "en" ? "Cover_letter" : "Lettre", contact, company, "pdf"));
writeFileSync(cvPath, await renderCvPdf(cv, fonts));
writeFileSync(letterPath, await renderLetterPdf(letter, fonts));
const letterText = [letter.salutation, ...letter.paragraphs, letter.closing, letter.signature].filter(Boolean).join("\n\n");
const kitPath = join(outDir, "kit.json");
writeFileSync(kitPath, JSON.stringify({ items: answerKit(content, master, apply, now, location), letter_text: letterText }, null, 1));
process.stdout.write(JSON.stringify({ cv: cvPath, letter: letterPath, kit: kitPath }));
