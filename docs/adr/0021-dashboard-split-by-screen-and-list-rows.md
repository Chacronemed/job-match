# ADR 0021: dashboard JavaScript split by screen, one row per offer, light tokens

**Status:** accepted, 2026-11-04

## Context

`dashboard.js` had grown to 2 900 lines holding every screen. The Offres table showed eleven
columns, fourteen rows at 1440×900, and needed three clicks to mark an application sent and two
to read the score's explanation. The page was dark only. A measured pass (Playwright on a
63-offer fixture, `docs/PROGRESS.md` 2026-11-04) gave the before numbers.

## Decision

1. **One file per screen.** `app.js` holds what every screen shares (data, helpers, theme,
   views and hash, tracking state and form, toast and optimistic save, record panel, palette,
   global keys); `why.js`, `list.js`, `tri.js`, `board.js`, `leads.js`, `runs.js` each own a
   screen; `dashboard.js` boots last. Files talk through one namespace, `window.JM`: values are
   read once at load, functions through the namespace at call time, so the load order only
   matters for the boot. The three reassigned scalars became properties (`JM.v.tab`,
   `JM.rec.open`...). A Node test checks that every `JM.x` read has an exporter.
   The pure modules (`tracking.js`, `triage.js`, `score.js`...) are untouched.
2. **The page ships the code without its comment lines** (`render.strip_comments`), which
   keeps the bundle under its previous size while the sources keep their notes.
3. **Offres: one row per offer.** Score (36 px bar + number), title with the status once
   handled, company, city, contract, age, the single strongest reason (a matched skill before
   the title family, its sentence in the tooltip), one expand. 34 px rows by default, 44 px
   "Confortable", remembered. Filters and sort stay in the hash and are also remembered for a
   bare hash. The expanded row opens on the actions (44 px on a phone), the meta line, the why
   ledger and the tracking form.
4. **Keyboard triage on the rows.** The focused row is the cursor: `j`/`k`, `x` drop, `s`
   keep, `a` "Candidature envoyée" (today, then the follow-up question), `Enter` opens the
   posting, `Space` expands, `o` the record, `/` the search, `?` the help. Writes are
   optimistic through the existing `applyChanges`: the row changes first, the undo toast
   follows, a refused save rolls back and says why.
5. **The why ledger.** Top-down: each matched skill with its weight and the sentence of the
   offer, the penalties, the title line, the experience gate (years, how they were found, the
   sentence), the score. Weights in one right-aligned column with tabular digits. The skills
   the offer cites that the profile lacks follow, marked "non compté", with « je maîtrise ».
   The preferred skills absent from the offer are no longer listed there: the engine did not
   use them.
6. **Light tokens.** `tokens.css` gains `:root[data-theme="light"]` on the same names; the
   inks are darkened until every visible text node passes AA on every surface, measured in
   both themes on every screen. The toggle is visible again.
7. **Candidatures and Leads, lightly.** Cards show the days in their status (from
   `updated_at`) and the follow-up date; an overdue follow-up is the only loud colour on the
   screen (red, with an icon). Leads show the hiring sentence under the signal and a jump to
   the company's offers.

## Measured (fixture: 47 listed rows, 14 applications; medians; `tests/unit/browser` green)

| | before | after |
|---|---|---|
| rows visible at 1440×900 | 14 | 21 |
| DOM nodes, Offres | 2 692 | 2 528 |
| domInteractive / first rows | 150 / 260 ms | 111 / 195 ms |
| dismiss an offer | 1 click (hover + quick action) | 1 key, row updated in 54 ms |
| mark « candidature envoyée » | 3 clicks | 1 key, 45 ms |
| open the score explanation | 2 clicks | 1 key |
| find a company by name | 1 click + 8 keys | 9 keys (`/` + name) |
| horizontal overflow at 390 px | 0 | 0 |
| text under AA | 1 (interview badge) | 0, both themes |
| `index.html` with the fixture | 395 617 B | 386 940 B |

## Alternatives

- A framework or a bundler: forbidden by CLAUDE.md, and the page must open from a file.
- ES modules instead of the namespace: the CSP hashes inline scripts; modules would need
  separate files and `script-src 'self'` only, which the Worker could serve, but the page
  then no longer opens from the file system (`file://` blocks module imports).
- Keeping the comments in the page: +27 KB over the previous bundle for the same features.
