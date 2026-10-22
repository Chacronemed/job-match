# ADR 0015: one dashboard design system (prototype C), with a self-hosted font and a split record panel

- Status: accepted
- Date: 2026-10-22

## Context

The dashboard was built on a system adapted from a marketing site. The UX audit (`docs/design/AUDIT.md`) found:
- text below AA contrast;
- scores that could not be reconciled;
- details that opened far from the row;
- copy and layout leftovers.

Two redesign directions (A « Relevé », B « Échelle ») lacked polish and life. A third direction was prototyped from public captures of Linear, Attio, Vercel and Raycast, and approved. It is ported one view at a time.

## Decision

1. **One system**, written in `docs/design/DESIGN.md`:
   - Radix slate dark on three surface levels, with violet as the single accent; status hues on dots only; 1 px semi-transparent borders; no gradients;
   - Inter at 13 px with tabular figures;
   - Lucide at 16 px / 1.5;
   - 40 px rows;
   - motion at 120–200 ms ease-out, off under reduced motion.
2. **Self-hosted Inter, CSP `font-src 'self'`.** `write_site` copies `fonts/InterVariable-latin.woff2` (OFL) and `LICENSES.md` next to `index.html`.
   - The font is a same-origin file, so no third party is called and the Access cookie goes with it.
   - Every other asset stays inline (CSS, JS, icons as nodes built with `createElementNS`).
3. **Dark only for now.** The theme code and its toggle are kept but the toggle is hidden. The light tokens are removed until light mode gets its own measured inks.
4. **The record panel** (one offer's details: properties, « Relevé », « Pourquoi », tracking) is shared by every view.
   - At 1280 px and up it is a third grid column: the list stays visible and keeps its columns.
   - Below 1280 it covers the page, which becomes inert.
   - Its state travels in the hash (`fiche=<key>`).
5. **Shared code in small UMD modules** (`lucide.js`, `score.js`, `ui.js`, `palette.js`), inlined in dependency order like `tracking.js` and `triage.js`. The pure parts (`score.js`, the palette's `match`) are tested under Node.
   - The views stay in `dashboard.js`, which owns the tracking state, the API client and the retry queue they share.
6. **Same data, same API.** `data.json`, the Worker API, scoring and the pipelines are unchanged. The « Relevé » is computed in the page from the scorer's explanation lines, which carry every weight. A capped score shows no start line rather than an invented one.

7. **The Tri card shows the whole description (step 1b, 2026-10-22).** `description_excerpt` (ADR 0014) keeps its name and its place in the allow-list, but now carries:
   - the full plain text, up to `DESCRIPTION_MAX = 5000` (France Travail's own cap), instead of 600 characters;
   - its line breaks, so the page can find sections and lists (`description.js`); everything is still set with textContent.
   - On the local DB (154 listed offers), `data.json` goes from 593 KB to 1 010 KB (gzip: 77 → 200 KB), and `index.html`, which inlines it, from 707 KB to 1 136 KB (gzip: 132 → 255 KB).
   - Alternative: load descriptions on demand from a second file. That means one more request per open and an extra code path for an offline page; rejected while the page stays under ~1.5 MB.

## Alternatives considered

- **Inline the font as a `data:` URI (`font-src data:`).** No extra file, but about 64 KB of base64 in every page load, parsed before first paint, and not cacheable on its own. Rejected.
- **System fonts only, as before.** No CSP change, but no control over figures, weights or the type scale; the direction depends on Inter's tabular figures and tight titles. Rejected.
- **An icon font or SVG sprite file.** It needs `font-src` or `img-src` for an asset that never changes colour on its own; inline nodes inherit `currentColor`. Rejected.
- **ES modules or a bundler.** The CSP and the single-file page rule out `<script src>`; a build step is forbidden unless a concrete problem requires it (CLAUDE.md). Rejected.
- **Record panel always as an overlay.** Simpler, but at desktop width it hid the columns being compared. Rejected; the overlay is kept below 1280 px.

## Consequences

- One more CSP directive (`font-src 'self'`) and two more files in `site/` (`fonts/`, `LICENSES.md`); `test_render.py` checks both.
- The views move one per commit. Until the last one, `dashboard.css` remains as a legacy sheet with its tokens remapped onto `tokens.css`.
- Light mode needs a later decision with measured contrast (AUDIT P1-6 stays open until then).
