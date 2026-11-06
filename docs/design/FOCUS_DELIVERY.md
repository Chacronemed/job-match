# Focus — delivery report

**Branch** `design/job-match-focus-inputs` · **PR (draft)** https://github.com/Chacronemed/job-match/pull/21 · 2026-11-06 · ADR 0025.
Contract: `docs/design/JOB_MATCH_FOCUS.md`, mockups: `docs/design/references/job-match-focus/`.
Everything below was run in the cloud session on the test fixtures (`tests/unit/conftest.py`
seed: three offers, one lead, 34 runs, a mocked `/api/applications`); no real data, no
deploy, no Worker, pipeline, scoring or workflow change.

## UI architecture

- **Shell.** `.app` grid: sidebar 232 px (brand, « Espace personnel », the five views with
  counts, « Accès rapide › Relances à faire » with the board's due count, « Rechercher
  partout ⌘K », the latest collection run with its date and error state, « Raccourcis ») |
  `.main-col` = 64 px top bar (breadcrumb « Mon espace / <vue> », snapshot date, theme
  toggle, phone-only search icon) + `#main`. The record `#record` is one node moved by
  `placeRecord()`: inside `#offres-split` on Offres at ≥ 1280 px, else the app grid's third
  column (≥ 1280 px) or an overlay drawer (< 1280 px), full screen above the tab bar on
  phones.
- **Views.** Each `.view` owns the space under the top bar with a `.page-top` (eyebrow,
  26 px title, counts from the data, actions). Offres and Tri scroll inside their panels,
  the others scroll as a whole. Phones: body scroll, 56 px sticky top bar, 64 px tab bar.
- **Stylesheets.** `tokens.css` (unchanged palette, `--sidebar-w`, `--topbar-h`, `--row-h`,
  `--panel-w` 420) + `app.css` (every component). `dashboard.css` is deleted and removed from
  `render.STYLESHEETS`. No gradient, no glass, one overlay shadow, Lucide 1.5, Inter self-hosted,
  CSP unchanged (`script-src 'self' + sha256`, no `unsafe-inline`, no CDN).
- **JavaScript** (same files, same `window.JM` contract): `list.js` draws the Focus rows,
  selection (`markSelected`, `ensureSelection`), the record footer (`recordActions`), the sub
  line; `app.js` the top bar crumb, `placeRecord`, the record body (score block, why ledger,
  AI view, collapsible announcement, tracking, documents, replies), the quiet open, the footer
  refresh; `tri.js` the card (score first, title, facts as chips, ledger, one quoted sentence,
  the announcement), the « Offre N sur T » line; `board.js` the stats line, the due chip,
  `dueKeys`, « Voir la fiche » on cards; `dashboard.js` the last run, the phone search button,
  « Trier les nouvelles », the sidebar quick link; `ui.js` exports `aiBlock`, ledgers open by
  default; `why.js` titles the ledger « Pourquoi cette offre te correspond ».

## Before / after

`docs/design/screenshots/focus/before/` (the 2026-11-05 dashboard) and `.../after/` (this
branch), captured by Playwright on the fixtures at 1440×900, 390×844, 1024×768 and 768×1024:

| View | After (dark) | Notes |
|---|---|---|
| Offres desktop | `offres-1440-dark.png`, `offres-record-1440-dark.png` | split view, first offer selected, record 420 px |
| Offres light | `offres-1440-light.png` | same layout, AA inks |
| Offres tablet | `offres-1024-dark.png`, `offres-768-dark.png` | drawer over the list, page inert |
| Offres phone | `offres-390-dark.png`, `offre-detail-390-dark.png` | single column, full-screen record, « Retour aux 3 offres » |
| Tri | `tri-1440-dark.png`, `tri-record-1440-dark.png`, `tri-end-1440-dark.png`, `tri-390-dark.png`, `tri-390-light.png` | 745 px card, actions above the tab bar |
| Candidatures | `candidatures-1440-dark.png`, `candidatures-1440-light.png`, `candidatures-table-1440-dark.png`, `candidatures-390-dark.png`, `candidatures-table-390-dark.png` | the four real columns, inbox, quiet due line |
| Leads / Exécutions | `leads-1440-dark.png`, `leads-390-dark.png`, `executions-1440-dark.png`, `executions-390-dark.png` | same panels, badges, funnels |
| Palette / help | `palette-1440-dark.png`, `help-1440-dark.png` | unchanged behaviour, Focus surfaces |

Two visual passes per view at least (pass 1 → 6 in the session scratchpad): score cell lost
to `max-width: 0` (fixed), top-bar search visible on desktop (fixed), record under the phone
top bar (fixed), double View Transition on the quiet open (fixed), status badge hue lost on
handled rows (fixed), stacked phone tables (restored), Tri ledger summary repeating the score
(fixed), 44 px targets and light-mode contrast (fixed, see QA).

## Functions preserved (checked by the tests named)

- Offres: search `/`, section chips (+ « Toutes »), department / source / status / AI / score /
  dates filters in the « Filtres » disclosure, sort from the header bar, hash + localStorage
  memory, dense / comfortable, `j k x s a Enter Space o ? /`, optimistic writes, undo toast,
  inline details with the why ledger and the tracking form, deep links `#offres?…&fiche=`
  (`test_offres.py`, `test_focus.py`, `test_render.py`).
- Record: title, company · place, status / contract / experience / age / source pills, real
  score and band, why ledger with sentences and the experience gate, « je maîtrise », AI view,
  announcement, grouped postings, tracking form with validation and rollback, verdicts,
  documents (generate / regenerate, PDF / DOCX rendered in the browser), answer kit with
  « Copier » and « Candidature envoyée », recruiter replies (`test_answer_kit.py`,
  `test_inbox.py`, `test_download_speed.py`, `test_apply_button.py`).
- Tri: queue and batches, ← → Z 1–4 ↵ keys, swipe (`ui.draggable`), retry queue, reasons bar,
  end screen (`test_focus.py` Tri tests, `worker/test/triage.test.mjs`).
- Candidatures: Kanban (drag with a fine pointer, status menu), table (« Générer les
  manquants », « Postuler », « Expirée »), inbox Valider / Corriger / Ignorer, due list,
  « J’ai postulé » with the follow-up question (`test_candidatures.py`, `test_inbox.py`,
  `test_apply_button.py`, `test_focus.py`).
- Leads (expand, « N offres » jump), Exécutions (« Lancer maintenant » ×2, AI passes, funnels,
  per-company boards), palette ⌘K with status changes, help `?`, theme toggle remembered,
  PWA manifest, tab bar badge.

## Tests (real runs, 2026-11-06)

| Family | Command | Result |
|---|---|---|
| Lint | `.venv/bin/ruff check .` | All checks passed |
| Full suite (fast + browser + worker) | `.venv/bin/pytest -q -n auto` | **1 722 passed, 3 skipped** (38.9 s) |
| Browser only | `.venv/bin/pytest -q tests/unit/browser -n auto` | 56 passed (11 in `test_focus.py`) |
| Worker (Node 22) | `npm ci --prefix worker && node --test` in `worker/` | 313 pass, 0 fail |

The 3 skips are pre-existing and unrelated to the UI: `tests/unit/documents/test_pdf_fonts.py`
checks the private `cv_master.yaml`, `contact.yaml` and `data/jobs.sqlite`, absent from a
clone (« checked locally only »); the baseline before any change was 1 711 passed, 3 skipped. CI uses `pytest -n auto`
as here. No test was skipped, weakened or removed; `test_render.py` needed no change
(the search keeps its example placeholder, the theme button its markup, the French-only
rule made the tab bar say « Exéc. » instead of « Runs »).

New in `tests/unit/browser/test_focus.py`: split view selects the first offer without taking
the focus and keeps the 420 px record inside the split; a click selects another offer and
keeps the filters, the unknown experience reads « Années non précisées »; drawer at 1024 with
`inert` and Escape back to the row; full-screen record on a phone with « Retour aux 3 offres »
and 44 px footer; footer « Garder » / « Candidature envoyée » / « Écarter » following the
status; section chips and « Toutes », sort bar; tracking error banner and footer reduced to
the link; Tri card 680–760 px centred, « Offre 1 sur 3 », → keeps, ↵ opens the record of
the triaged offer; phone Tri actions above the tab bar, 44 px; board counts, due chip, card
→ record, phone stacking and table without overflow.

## QA audit (script in the session scratchpad, both themes, 1440 / 390 / 768 / 1024, six screens)

- **Console:** 0 errors on every screen (the only logged request is the mocked
  `content.json` 404 of the fixtures' documents, as before the redesign).
- **Horizontal overflow:** 0 px everywhere.
- **Contrast:** every visible text node ≥ 4.5:1 (≥ 3:1 for 24 px+) in dark and light after
  the lot-4 fixes (the selected row's greys moved to `--ink-2`, the status badge keeps its
  hue). The audit's only remaining lines are the two scale-threshold labels, a false positive
  of the ancestor-background heuristic (they sit on `--raised`, 5.3:1 / 5.9:1).
- **Targets at 390:** every reachable control ≥ 44 px (the only remainders are the
  `aria-hidden` back card of the Tri pile, scaled 0.95 and `pointer-events: none`).
- **Reduced motion:** `prefers-reduced-motion` kills every animation and transition
  (`tokens.css`, `app.css`); the quiet open and the phone record use none.
- **Keyboard only:** covered by the Offres and Tri key tests; visible focus rings unchanged
  (2 px violet, `:focus-visible`).

## Remaining gaps with the mockups, and why

- **Top-right avatar « JM », « Exporter », « + Nouvelle candidature », the « ⋯ » menus on
  cards:** not shown, nothing in the app backs them (the contract forbids inventing).
- **« Garder et préparer »** reads « Garder » (with the arrow): keeping is what the button
  does; the documents follow by the Worker's own rule, so the label does not promise more.
- **Section tabs** stay multi-toggle chips (the app's hide= semantics) with a « Toutes »
  reset, instead of single-choice tabs.
- **« OFFRES · TRIÉES PAR SCORE / Filtres ⌄ ⋮ »** became two slim lines: « Filtres (n) » with
  the row count, then the sort bar « Trier par » (the table's own `th` buttons, kept for the
  sort and the tests).
- **The Tri card** shows the whole announcement under the quoted sentence (the contract
  preserves the description); the mockup shows the quote only.
- **Kanban cards** keep the status menu, « J’ai postulé » and « Offre » in their footer
  (real actions) next to « Voir la fiche »; the mockup footer has « Voir la fiche ⋯ » only.
- **Fixture data** shows three offers, so the lists are short and one title is the XSS
  probe; the mockups' nine rows and employers are fictitious.
- **Phone « Fiche de l’offre » page top** is folded into the record bar (« ← Retour aux N
  offres · OFFRE SÉLECTIONNÉE »), the title being the offer's own.
- The **record panel** is 420 px (contract: 404–440), the sidebar 232 px (220–232), rows
  58 / 70 px (contract ~68–72 in comfortable terms; dense stays a user setting).

## Limitations

- Tested in headless Chromium only (Playwright); Safari's `env(safe-area-inset-*)` and
  `100dvh` are used as before, not measured here.
- Light mode is derived from the same rules; the mockups illustrate dark only.
- The audit script lives in the session scratchpad (not committed): it mirrors the
  2026-10-21 `AUDIT.md` method (text-node contrast, 44 px targets, overflow, console).
- `gh` is not authenticated in the session; the PR was opened through the GitHub API tool.

## Commits (oldest first)

1. `1fcb138` feat(ui): Focus shell and Offres split view with the record panel
2. `39efa84` feat(ui): Focus Tri card, phone offers list and record
3. `7a770ef` feat(ui): Focus Candidatures board and table, phone targets
4. `ed3fb4f` fix(ui): AA contrast on the selected row, 44 px targets on phones
5. docs(ui): Focus delivery report, after screenshots, ADR 0025, PROGRESS
6. chore: drop the Focus input archive from the branch
