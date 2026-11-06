# ADR 0025: the « Focus » dashboard layout

**Status:** accepted, 2026-11-06

## Context

The dashboard was a Linear-style table (one 34 px row per offer, a record panel as a third
column at ≥ 1280 px) with four views still on the legacy `dashboard.css`. The Focus design
contract (`docs/design/JOB_MATCH_FOCUS.md`, five mockups in
`docs/design/references/job-match-focus/`) imposes one art direction: a flat canvas, panels
on `--surface` with an 11 px radius, a 232 px sidebar, a 64 px top bar, Offres as a split
view (list + selected record), Tri as one wide centred card, Candidatures as a four-column
board, a bottom tab bar and a full-screen record on phones. The counts and texts of the
mockups are fictitious; only their layout is prescriptive. Every existing function, DOM
contract used by the tests (`id`, `data-*`, the hash, `window.JM`) and the CSP had to stay.

## Decision

1. **One stylesheet.** `dashboard.css` is deleted; `app.css` holds every component, on the
   tokens of `tokens.css` (unchanged palette, three new layout tokens: `--sidebar-w`,
   `--topbar-h`, `--row-h`; `--panel-w` 440 → 420). Light mode keeps the same rules.
2. **The record panel moves, the DOM contracts do not.** `#record` is one node; `placeRecord`
   (app.js) appends it inside `#offres-split` when Offres is shown at ≥ 1280 px
   (`body.record-split`, a 420 px grid column next to the list) and back into `.app` for the
   other views (a third column) or below 1280 px (the overlay drawer; full screen above the
   tab bar on phones, with a « Retour aux N offres » button). A row click selects the offer and
   opens its record; the chevron and Space keep the inline details. At ≥ 1280 px the first
   listed offer is selected quietly (no focus move, no View Transition) when nothing is.
   *Alternative:* a second record component for the split: rejected, two code paths for the
   same actions.
3. **The Offres table stays a table.** The sort, the cells and the tests keep `th[aria-sort]`,
   `td.col-*`; CSS draws `thead` as a sort bar and each `tr.row` as a two-line Focus row
   (monogram, title, the quiet facts, the score and its band word). The hidden sortable cells
   stay in the DOM. Dense (58 px) and comfortable (70 px, with the strongest reason as a third
   line) remain a user setting.
4. **The record's footer carries the real actions only.** « Voir l’annonce », « Garder »
   (`to_apply`), « Candidature envoyée », « Écarter », from `list.js`'s own `quickSet` /
   `markApplied`; redrawn by `refreshBadges`. No « Exporter », no « Nouvelle candidature »:
   nothing backs them.
5. **Counts come from the data.** Page tops read the rows, the board and the runs
   (`renderSub`, `renderStats`, `#last-run`); « Relances à faire » in the sidebar is
   `board.js`'s own due list. The Tri card quotes one real sentence of the offer (the best
   matched skill's snippet) and says « Années non précisées » when the posting states no
   number.

## Consequences

- Every browser test of 2026-11-04 to 11-06 passes unchanged, plus `tests/unit/browser/
  test_focus.py` (split view, drawer, phone record and back, footer actions, sections, error
  state, Tri card and phone actions, board counts and phone stacking).
- `docs/design/DESIGN.md` (phase 3) is superseded by this layout; `docs/design/
  FOCUS_DELIVERY.md` records the before/after captures and the remaining gaps.
- The CSP, the Worker, the pipeline and the scoring are untouched.
