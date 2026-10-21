# Dashboard UX audit

**Revision 2** (2026-10-21, before the UI redesign). It replaces the first pass from the same
day; the IDs are kept. No code was changed for this revision.

Out of scope: scoring, pipelines, SQLite, the Worker API and the data.json fields.

## Method

- **Data:** fake only, in the session scratchpad (`…/scratchpad/audit/`).
  - `seed.py` builds the data with the real `write_site`: 59 offers, 4 tracked closed offers,
    8 leads, 12 runs.
  - `seed.sql` holds 23 rows for the scratch D1, reset before this pass.
  - Nothing is read from the real DB, the profile or `site/`.
- **Stack:**
  - `wrangler dev` (scratch config) behind `scripts/dev-access-proxy.mjs`;
  - playwright-cli in Chromium with an en-US browser locale;
  - viewports 1440×900 and 390×844, dark and light. The theme was checked through
    `data-theme` before naming each shot.
- **Measured:**
  - clicks per journey;
  - element boxes against the viewport;
  - text contrast over every visible text node, both themes (`contrast.js`);
  - interactive boxes under 44 px at 390 (`targets.js`);
  - horizontal overflow: 0 everywhere;
  - console errors: 0.
- **Guidelines:** the Vercel Web Interface Guidelines, fetched again for this pass (104 rules).
  They were applied to `index.template.html`, `dashboard.css`, `dashboard.js`, `tracking.js`
  and `triage.js`.
- **Screenshots** stay outside the repo (it is public), in `…/scratchpad/audit/shots/`:
  - `p1-*`: this revision. `p1-<view>-<width>-<theme>[-full].png` for the views, `p1-S-*`,
    `p1-T-*`, `p1-R-*`, `p1-F-*` for the journeys.
  - `fix-*`: after the P1 fixes.
  - `jA-*` / `jB-*` / `jC-*`: the first pass, before the fixes.
  - The `audit-*` shots were re-taken during this pass and now show the state after the fixes
    (identical to `p1-*`). The "before" evidence for P1-1 to P1-3 is in `jA-*` / `jB-*` /
    `jC-*`.

## Status of the first-pass findings

| ID | Status | Evidence |
|---|---|---|
| P1-1 follow-up prompt off-screen | **Fixed**, re-verified. The question is in a held toast, focused; Escape = Non; Annuler reverts. | `fix-B-toast-1440-dark.png`, `fix-B-toast-390-light.png` |
| P1-2 substring search | **Fixed**, re-verified. Word-based, accent-folded, any order, location included. | `fix-C-results-390-dark.png` |
| P1-3 misplaced reason bar | **Fixed**, re-verified. The question names the offer, takes the buttons' place, and never shows at batch end. | `fix-A-reasons-390-dark.png`, `fix-A-end-390-dark.png` |
| P1-4 no years on the Tri card | **Fixed**: "1 an requis" / "années non précisées". | `fix-A-card-390-dark.png` |
| P2-11 pending counts calls | **Fixed**: "2 offres" after 2 keeps (4 calls). | `fix-pending-1440-light.png` |
| P2-16 `aria-live` on `.kpis` | **Fixed**. | — |
| P2-6 toast covers content (390) | **Partial**. The toast now spans the screen width, but it still covers the bottom card while held. | `fix-B-toast-390-light.png` |
| P2-2, P2-5 | **Open, raised to P1**: the new journeys T and R show they block. | below |
| All other first-pass items | **Open, unchanged**. Contrast re-measured: the same values. | `p1-*` |

## Journeys

### A. Sort today's offers (after the fixes)

Measured at 390 dark and 1440 light; the plan was 13 keeps and 7 drops.

| Steps | Actions |
|---|---|
| 20 decisions, 3 reasons, 3 "Passer", 1 undo + 1 redo | **28** for 20 offers (the first pass: 26) |

- Resuming after "Lot suivant" works.
- ← shows the reason step; → or Escape skip it.
- Offline: 2 keeps give "2 offres en attente", and "Réessayer" sends them.

Hesitations:
- **A7:** with the buttons, a drop without a reason costs a tap on "Passer" or a 6 s wait
  (P2-22).
- **A8:** the card shows a score colour (green, blue or amber) but never what it means
  (P1-8).

### S. Understand a score and its reasons (new)

| Width | Path | Clicks |
|---|---|---|
| 1440 | Tri card → Offres → search the title → expand the row → open "Pourquoi cette offre ?" | 4 + typing |
| 390 | same, plus "Filtres" | 5 + typing |

Hesitations:
- **S1 (blocking):** the Tri card links only to the job board ("Voir l'offre"). Nothing opens
  this offer's details: `openInJobs` exists in `dashboard.js` but is never called.
- **S2 (blocking):** searching the title "DevOps Engineer" gives 9 rows with the same title. The
  first one opened was another company's offer, and nothing flags the mix-up (P1-9).
- **S3:**
  - The "Pourquoi" panel is closed by default. Its summary sits at y 596 at 1440, and at
    y 1378 at 390 (about 1.6 screens down, under the tracking form).
- **S4 (blocking for "why 63 and not 80"):**
  - The panel lists weights (+1, +2, +2) beside a score of 83. Nothing shows how they make 83:
    no total, no baseline, no "Forte ≥ 75 / digest ≥ 50" next to the figure.
  - The thresholds appear only in the Offres slider hint (P1-8).
  - Shots: `p1-S-why-1440-dark.png`, `p1-S-why-390-light-full.png`.

### C. Filter (after the fixes, plus combinations)

| Width | Clicks |
|---|---|
| 1440 | 3 + typing |
| 390 | 5 + typing |

- **Works:**
  - combined filters (section + department + score ≥ 70 → 2 offers);
  - "Filtres (3)";
  - the shared URL reopens the same 2 offers;
  - "Réinitialiser" clears the filters and the hash.
- **C5:** no list of the active filters (which 3?): only the count, inside the panel (P2-23).
- **C6:** the empty state "Aucune offre ne correspond à ces filtres." has no reset action
  (P2-23, `p1-F-empty-1440-dark.png`).

### T. Track an application (new)

| Action | Cost | Result |
|---|---|---|
| Envoyée → Entretien via the status menu | 1 | The toast says "Déplacée vers « Entretien » · Annuler"; the card moves |
| Same, by drag (1440) | 1 drag | Works |
| See the note or the CV of an application | not possible on the board | — |

Hesitations:
- **T1 (blocking for keyboard and screen-reader users):**
  - after a status change from the menu, the card is re-rendered in another column and focus
    falls to `<body>`;
  - at 390 the moved card is also off-screen (P1-10, `p1-T-moved-390-light.png`).
- **T2:** the card title is plain text, and the note ("Relance par mail au recruteur" in the
  fake data) is not shown anywhere on the board (P2-2, raised to P1).
- **T3:** the 4 tracked offers that are closed or past the age cut-off show no "fermée" marker
  (P2-24).

### R. Follow up (new)

| Width | Path | Clicks |
|---|---|---|
| 1440 | "Relances dues" item → (the card only has the status menu and "Offre") → Offres → search → expand → "Relance le" date | 5 + typing |
| 390 | same, plus "Filtres" | 6 + typing |

Hesitations:
- **R1 (blocking):**
  - There is no "Relancé" action and no date control on the board.
  - Moving the follow-up date means leaving Candidatures for Offres (P2-5, raised to P1).
- **R2 (blocking):**
  - The search by title found several "Administrateur systèmes Linux" rows. The date was saved
    on the wrong offer, so after reloading the board still showed 2 follow-ups due.
  - Nothing warned about it. This is the same cause as S2 (P1-9).
- **R3:** the due item scrolls to the card and focuses it, but programmatic focus shows no ring
  and there is no highlight, so it is hard to see which card it is (P2-25,
  `p1-R-due-390-light.png`).

## Findings

Priorities:
- **P1:** blocks or slows a key journey, or fails accessibility.
- **P2:** friction or an inconsistency.
- **P3:** polish.

"Impact" says who is hindered and how often.

### P1 (open)

| ID | View | Category | Issue | Impact | Proposed fix | Shots |
|---|---|---|---|---|---|---|
| P1-5 | All | Accessibility | Text under AA:<br>• tab counts: 3.62 dark / 3.25 light, 12 px<br>• field hint, "/ 58", "—": 3.0–3.3<br>• "Entretien": 3.17<br>• "retraitement": 2.65 (light) | Every screen, both themes | Darken `--ink-subtle`/`--ink-tertiary` where they carry text; give every status ink a ≥ 4.5 pair | `p1-offres-1440-light.png` |
| P1-6 | All (light) | Accessibility | Accent `#5e6ad2` on white: 4.34 (links, "Voir l'offre", "Ouvrir", "Nouveau"). Success ink: 4.08 (skills, "Garder", "Candidature envoyée"). | Every light-mode screen | Darker light-mode link and success inks; keep the hue | `p1-tri-1440-light.png` |
| P1-7 | Offres (390) | Hierarchy | Result cards about 290 px each, so the list is about 16,700 px. With the filters open, results start below the fold. | Every phone search | A 2-line row (title; company · dép. · score · âge), actions in the details | `p1-offres-390-dark-full.png` |
| P1-8 | Tri, Offres | Readability | The score is not explained:<br>• its colour has no legend;<br>• the thresholds (forte ≥ 75, digest ≥ 50) sit only in the slider hint;<br>• the "Pourquoi" panel lists weights that don't visibly add up to the figure. | Every decision (S4, A8) | Name the band next to the figure ("Forte · ≥ 75"), from `data.thresholds`; show the stored explanations as the breakdown, open by default, instead of folded under "Toutes les explications". No scoring change. | `p1-S-why-1440-dark.png` |
| P1-9 | Tri, Candidatures | Interaction | Neither card opens its offer's details (why panel, note, CV, dates); `openInJobs` is dead code. The workaround (searching the title) hits same-title offers and edited the wrong one in R2. | Score (S), tracking (T), follow-ups (R): daily | Card title → opens that exact offer's details, matched by key (not by title search). Reuse `openInJobs` with a key filter. | `p1-S-why-1440-dark.png` |
| P1-10 | Candidatures | Accessibility | After a status change from the menu, focus falls to `<body>`; at 390 the card is off-screen. | Every keyboard or screen-reader status change | Focus the moved card's menu (or the column heading) and announce "Déplacée vers « Entretien »" | `p1-T-moved-390-light.png` |
| P2-2 → P1 | Candidatures | Interaction | Note, CV and follow-up date are not shown or editable on the board (T2). | Every follow-up | A note excerpt and a "Relance 25/10" control on the card; or P1-9's details link | `p1-candidatures-1440-dark.png` |
| P2-5 → P1 | Candidatures | Interaction | No "Relancé" action; moving a follow-up date takes 5–6 clicks and a change of view (R1). | Every due follow-up | On each due row and card: "Relancé (+7 j)" and "Autre date", the same pattern as the follow-up toast | `p1-R-due-1440-dark.png` |

### P2 (open)

| ID | View | Category | Issue | Impact | Proposed fix | Shots |
|---|---|---|---|---|---|---|
| P2-1 | Candidatures (390) | Hierarchy | Stacked columns: Entretien starts about 2,000 px down | Phone use of the board | A column switcher with counts | `p1-candidatures-390-dark-full.png` |
| P2-3 | Candidatures | Hierarchy | Every to_apply card has a filled primary "J'ai postulé" (up to 30 accents) | Every visit | Make it a secondary button; one accent per screen | `p1-candidatures-1440-dark.png` |
| P2-4 | Candidatures | Consistency | The status menu repeats the column title; Refus weighs as much as the active columns | Every visit | A compact "Déplacer…" menu; mute or collapse Refus | `p1-candidatures-1440-light.png` |
| P2-6 | Candidatures (390) | Layout | The held toast covers the bottom card | Every application on a phone | Pad the page bottom by the toast's height while it is shown | `fix-B-toast-390-light.png` |
| P2-7 | Tri | Consistency | Skills listed twice: weights, then chips | Every card | One chip row carrying the weight | `p1-tri-1440-dark.png` |
| P2-8 | Tri | Readability | "Lot 1/3 · 2 / 20 · 41 restantes": three counters in 12 px | Every card | Batch progress prominent, total secondary | `p1-tri-390-dark.png` |
| P2-9 | Tri | Interaction | After a mouse click on a tab, ← → switch tabs instead of deciding | Keyboard triage | Focus the card when Tri is opened with the pointer | `st-focus-tri-1440-dark.png` |
| P2-10 | Tri | Copy | "Plus tard" is vague; "depuis le début" means "this session" | Every batch end | "Voir mes candidatures" / "Arrêter là"; "aujourd'hui" | `fix-A-end-390-dark.png` |
| P2-12 | Offres | Consistency | Read-only status pills look like the action pills | Every row | Status as a dot plus text; actions as outlined buttons | `p1-offres-390-dark.png` |
| P2-13 | Offres | Hierarchy | Details open on the tracking form; the excerpt is missing; "Pourquoi" is closed and sits 1.6 screens down at 390 | Score journey (S3) | Excerpt, then "Pourquoi" (open), then tracking | `p1-S-why-390-light-full.png` |
| P2-14 | Offres | Interaction | No relative-age filter | Finding old offers | "< 7 j · < 30 j · > 30 j" chips that set the dates | `jC-results-1440-dark.png` |
| P2-15 | Offres | Readability | "?" for an unknown department | Many rows | "—" with "non précisé"; a filter option | `p1-offres-1440-dark.png` |
| P2-17 | Offres (390) | Hierarchy | About 220 px of KPI tiles above the filters | Every phone visit | A one-line summary | `p1-offres-390-dark.png` |
| P2-18 | Exécutions | Copy | Raw reason keys (`off_topic`, `reserved_rqth`…) | Every run card | A French label map | `p1-executions-1440-dark.png` |
| P2-19 | Exécutions | Hierarchy | The error badge looks like "retraitement"; two near-greys; no summary of the last run | Run checks | A red badge; a distinct hue; a status line at the top | `p1-executions-1440-dark.png` |
| P2-20 | Leads | Readability | "4.5 M€" (English decimal, monospace) wraps on phones | Every lead | `Intl.NumberFormat("fr-FR", {notation: "compact"})` | `p1-leads-390-light.png` |
| P2-21 | Leads | Interaction | Rows expand with no cue; the "Offres" count is not a link | Every lead | A chevron; the count links to `#offres?q=<entreprise>` | `p1-leads-1440-dark.png` |
| P2-22 | Tri | Interaction | The reason step hides the buttons; button users pay a "Passer" tap per drop without a reason (A7) | Every drop without a reason | Keep compact Écarter / Garder in the reason step; the next decision closes it without a reason | `fix-A-reasons-390-dark.png` |
| P2-23 | Offres | Interaction | Active filters are not listed (only "Filtres (n)"); the empty state has no reset (C5, C6) | Every filtered search | A row of active-filter chips with ×; "Réinitialiser les filtres" in the empty state | `p1-F-empty-1440-dark.png` |
| P2-24 | Candidatures | Readability | Tracked offers that are closed or too old are not marked (T3) | Long-running applications | An "offre fermée" / "plus listée" badge from the `tracked` list | `p1-candidatures-1440-dark.png` |
| P2-25 | Candidatures | Accessibility | A due item focuses its card with no visible ring or highlight (R3) | Every follow-up | Style `.kb-card:focus` (programmatic), or a 2 s highlight | `p1-R-due-390-light.png` |
| P2-26 | All (390) | Accessibility | Targets under 44 px:<br>• "Voir l'offre" 65×21; kanban "Offre" 31×21; "Toutes les explications" 28;<br>• sort headers, section chips and the why summary: 36;<br>• search, selects, "Réinitialiser", theme toggle and skip link: 37–38;<br>• toast actions: 32 px, reason chips: 36 px (CSS) | Every phone visit | `min-height: 44px` under 768 px for every control; enlarge the text links' hit area | — |

### P3 (open)

| ID | View | Category | Issue | Proposed fix | Shots |
|---|---|---|---|---|---|
| P3-1 | Offres (390) | Typography | "Filtres(2)": no space before the count | A gap on `#filters-count` | `fix-C-results-390-dark.png` |
| P3-2 | Offres | Hierarchy | A sort glyph on every header | Show it only on the active column and on hover/focus | `p1-offres-1440-dark.png` |
| P3-3 | Offres | Consistency | Quick actions lose their pill style in an expanded row | One style | `p1-S-why-1440-dark.png` |
| P3-4 | Offres | Performance | Every row is rendered (59 here, a few hundred in real use) | `content-visibility: auto` on rows | — |
| P3-5 | Offres | Layout | The slider hint wraps to 2 lines at 1440 | Shorter hint (it moves next to the score with P1-8) | `p1-offres-1440-dark.png` |
| P3-6 | Header (390) | Hierarchy | "Mode clair" is a large text button | An icon button with an `aria-label` | `p1-tri-390-dark.png` |
| P3-7 | All | Theming | `theme-color` follows the system, not the toggle | Update the meta tag in `applyTheme` | — |
| P3-8 | Tri | Interaction | "Lire la suite" is small; "Voir l'offre" sits far from the controls | Bigger targets (P2-26); move the link | `p1-tri-390-dark.png` |
| P3-9 | Offres / Candidatures | Locale | Date inputs follow the browser locale (`mm/dd/yyyy` on en-US) | Nothing on fr-FR; optionally show the date in words | `p1-S-why-1440-dark.png` |
| P3-10 | Design system | Consistency | `DESIGN.md` still carries the marketing system it came from: pricing tabs, an 80 px display size, footer, "lead every section with a product screenshot". It also has a stale `today-view` and English UI strings ("Saving…", "Saved", "Open") in `track-form`. | Rewrite it as the single dashboard system (phase 2 of the redesign) | — |

## Fix status

Fixed on 2026-10-21: P1-1, P1-2, P1-3, P1-4, P2-11, P2-16. P2-6 is partial. The counts below
are from the re-run journeys, same fake data:

| Journey | Before | After |
|---|---|---|
| A. Sort 20 offers | 26 actions | 28 actions (+3 "Passer", see P2-22); the question is about the right offer and in the right place |
| B. Apply + follow-up | 3 (1440) / 4 (390) clicks, question off-screen | 3 / 5 clicks, question in the focused toast; "Enregistrer" is explicit |
| C. Old offer | 4 / 5 clicks, "orbital kubernetes" found 0 | 3 / 5 clicks, found with no date filter |
| S. Understand a score | — | 4 / 5 clicks + typing, and the score still can't be reconciled |
| T. Status change | — | 1 action; focus lost |
| R. Move a follow-up | — | 5 / 6 clicks + typing, a change of view, a risk of editing the wrong offer |

Counts: **8 P1 open** (P1-5 to P1-10, P2-2, P2-5), **22 P2 open** (P2-6 partial), **10 P3
open**, 6 fixed.

## Guidelines (revision 2: new or changed only)

- **Focus States:** focus is lost after a board status change (P1-10). Programmatic focus on
  the card has no visible style (P2-25).
- **Touch & Interaction:** targets under 44 px on phones (P2-26).
- **Accessibility:** the held toast is `role="status"` and polite: its buttons are announced
  and reachable, and focus moves into it. OK.
- **Forms:** the toast's date input has an `aria-label`, `name`, `autocomplete="off"`, and
  saves only on an explicit action. OK.
- **Unchanged since the first pass:** contrast (P1-5, P1-6); `theme-color` (P3-7); more than
  50 rows unvirtualized (P3-4).
- **Passes:** reduced motion (rules present), no `transition: all`, no zoom block, a skip
  link, `Intl` dates, URL-synced filters.

## Accepted deviations (not re-raised)

- **Sentence case, not Title Case:** the UI is French.
- **First-person labels ("J'ai postulé", "je maîtrise"):** the owner's own voice.
- **No `inert` on a dragged kanban card:** it would break pointer capture.
- **The Tri position is not in the URL:** it is session state.
- **Kanban columns are not virtualized:** each holds well under 50 cards.
- **Hover colour transitions:** short, and on colour only.
