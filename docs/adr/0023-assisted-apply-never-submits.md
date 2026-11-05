# ADR 0023: assisted application: an answer kit, a form filler that never submits

**Status:** accepted, 2026-11-05

## Context

Once an offer has its CV and letter (ADR 0017), the application itself is still typed by
hand: name, email, phone, links, two file uploads, and the same questions on every form
(motivation, why this company, availability, notice, mobility, work authorization, salary).
Greenhouse, Lever and Ashby carry most of the `ats` source (ADR 0020). The tool must save that
typing without ever acting for me: **it never presses Send / Submit, never creates an
account, never solves or bypasses a CAPTCHA**, and invents nothing, the salary least of all.

## Decision

1. **The kit is part of the documents call** (prompt v6). `DOCUMENT_SCHEMA` gains
   `answers: {motivation, why_company}`, each a list of sentences `{text, sources}`: one call,
   the cached system block, the same monthly budget (`ai_usage`, ADR 0017) and the same
   targeted retry (an answer error sends back that answer only). The validator applies the
   letter's rules to every sentence (numbers, tools, employers and contexts from the cited
   bullets, past tense for finished experiences, no unknown name) plus: 1 to 3 sentences, 600
   characters at most, no salutation, `why_company` names the offer's company, and neither
   speaks of availability, notice, salary or pay (`answer_scope`). `max_tokens` 3 000 → 3 600.
   *Alternative:* a separate kit call per offer: a second prompt, a second budget path, more
   cost; rejected.
2. **Everything else in the kit is computed, never generated** (`worker/src/kit.js`, pure,
   no import, shared by the Worker, the offer page and the local filler): availability from
   the master's `available_from` (the function moved here from documents.js), mobility from
   the master (or `mobilite`), notice and fixed answers (`reponses_fixes`: label, match words,
   answer) from **`private/apply.yaml`** (gitignored; `config/apply.example.yaml`), pushed to
   R2 as `master/apply.json` by `job-match cv push` and added to the content bundle (`apply`,
   null when absent).
3. **Salary:** `remuneration.mode: manuel` (the default, and the value when apply.yaml is
   missing) means a salary field is never filled, anywhere: the kit item has no text and no
   « Copier », the filler outlines the field in red and prints the zone's benchmark
   (`reperes`: the first zone whose word is in the offer's location, else the default zone).
   In `manuel`, `cv push` drops the range from apply.json: no salary value leaves the machine.
   `mode: fourchette` pastes my range in a text field, picks a select option only when exactly
   one sits inside the range (else « hors fourchette »: left), and never types a single figure
   in a number box.
4. **`job-match apply <job_key>`** (local only, `src/job_match/apply/`): the offer URL from
   the jobs DB (or `--url`), the latest ready version from D1 and its content.json from R2
   through the local `wrangler login` (as `cv push`), the CV and letter PDF rendered here by
   the dashboard's render.js (`scripts/apply-render.mjs`) into `private/out/apply/`, then a
   visible Chromium on a persistent profile (`private/browser-profile/`) on the application
   page (Lever `/apply`, Ashby `/application`, Greenhouse the job page).
   - ATS by host; anything else: « formulaire non pris en charge », the page stays open.
   - Fields are classified from label / name / id / placeholder / autocomplete with the words
     of `config/apply_questions.yaml`, in a fixed order: sensitive (EEO, disability,
     diversity, age, nationality…) and consent first, never filled; then salary; then fixed
     answers; then contact fields, files, the kit. A bare « Name » is my name only when it is
     the whole label (never « Company name »). Checkboxes are never ticked; password fields
     never written.
   - Writes use `fill`, `select_option`, `set_input_files`, and `check` on a radio only
     (verified to be one). **No click anywhere else**: no button, link or checkbox.
   - A visible CAPTCHA or a sign-in page: pause, « à toi », Enter to go on.
   - The terminal report names each field and the source of its value, never the value.
     The browser stays open until Enter: I review and send myself.
5. **`job-match apply <key> --sent`** (or « Candidature envoyée » in the offer page): status
   `applied`, `applied_at` today, `follow_up_at` +7 days (`--follow-up-days`); the Worker's
   existing rule records `sent_documents_version`, the CLI writes it from the latest ready
   version. A second `--sent` keeps the first dates.
6. **The offer page** shows « Kit de réponses » under Documents for a ready version: each
   answer with « Copier », the notes of what is missing (an older v5 version: regenerate).

## Tests

`tests/fixtures/apply/` holds Greenhouse, Lever and Ashby forms (Ashby rendered late, like its
SPA), an unsupported page and a CAPTCHA page; every page loads `guard.js`, which records any
press of a button or link and any submission. `tests/unit/browser/test_apply_forms.py` runs
the filler in Chromium with every request answered locally (anything else aborted, any non-GET
recorded): filled fields, unknown / sensitive / consent fields empty and outlined, and each
test fails if anything was pressed or sent. A parametrized test fails if a salary field is
filled in `manuel` on any of the three forms, another if a range smuggled into the kit is used.
`worker/test/kit.test.mjs` covers the kit and the answers validator,
`tests/unit/browser/test_answer_kit.py` the offer page.

## Consequences

- Every ready version before prompt v6 has no motivation / why_company: the kit says so and
  « Regénérer » makes one (one documents call).
- Fixed answers on a select or a radio: see the amendment below.
- Embedded Greenhouse forms on a company's own site (iframe) and Workday / SmartRecruiters
  forms are « non pris en charge » for now.
- The answer kit costs a few hundred output tokens per document within the same budget.

## Amendment, 2026-11-05: bilingual options for fixed answers

A fixed answer written in French (« Oui », « Permis B », « CDI ») now finds the option of an
English form. The option may read, folded (case and accents ignored): the answer; its optional
`label_en` in apply.yaml (`reponses_fixes[].label_en`, the exact English option text when it is
a sentence: « No, I do not need sponsorship »); or any member of an `option_equivalents` group
in `config/apply_questions.yaml` holding one of them (oui/yes, non/no, permis B/driving licence
B, CDI/permanent, CDD/fixed term, temps plein/full time, télétravail/remote, hybride/hybrid,
sur site/on-site; quoted, since YAML 1.1 reads a bare yes / no as a boolean). Exact matches are
tried first, in that order; then the single option starting with one of them as a whole word
(« no … » never matches « None »). No match, or several: left and listed, never guessed.
Tested on an English form (`tests/fixtures/apply/english.html`).
