# JOB MATCH — FOCUS / Design contract v1.0

**Status: imposed art direction. Do not start a design exploration.** These screenshots are prescriptive visual references for layout, visual hierarchy, density, treatment of text, cards, selected row, filters and responsive modes. The fictitious content and counts are **not** prescriptive. The application MUST show its actual existing data.

## Sources of truth and priorities

1. **Functional truth:** `CLAUDE.md`, existing code, APIs, existing tests, `docs/ARCHITECTURE.md`; no functional/data/security regression.
2. **Visual truth:** the five PNGs in `docs/design/references/job-match-focus/`, then this contract. Source `reference.html` illustrates spacing and layout but is a static NONPRODUCTION sketch. Copy visual intent only, not mocked data or fake interactions.
3. **Tokens:** `src/job_match/dashboard/assets/tokens.css` and `docs/design/DESIGN.md`, adjusted only as needed to match screenshots. Keep existing dark/light contrast guarantees.
4. **Where visual references and existing behavior conflict:** preserve behavior and adapt reference visually; document a short note, never silently delete a feature.

## Exact visual direction

- Design name: **Focus**. Original visual system for Job Match; **do not copy Linear/Attio/Huntr/Teal logos, screenshots, brand text or trademarked visual assets**.
- Desktop screenshot target: **1440 × 900**. Mobile target: **390 × 844**. Also test **768 × 1024** and **1024 × 768**.
- Theme: dark default, graphite/slate black; light theme must remain usable with equivalent hierarchy.
- Palette: `--bg:#111113`, `--surface:#18191b`, `--raised:#212225`, `--ink:#edeef0`, `--ink-2:#b0b4ba`, `--ink-3:#91959e`, `--accent:#6e56cf`, `--accent-ink:#baa7ff`; green `#3dd68c`, amber `#ffca16`, red `#ff9592`, blue `#70b8ff` ONLY for semantic state and score highlights. Avoid gradients, glassmorphism, decorative glows, emojis as UI icons, heavy shadows and arbitrary accent hues.
- Typography: existing self-hosted **Inter Variable**, system fallback; default 13px, title desktop 26px, mobile 23px, row title 13px, explanations 11–12px; tabular numerals for score/dates. Maintain readable WCAG AA contrast (no tiny muted contrast shortcuts).
- Shape: 4px spacing grid, radii 6/8/11px, strokes 1px `rgba(255,255,255,.085)`, restrained hover. Lucide icon stroke 1.5px. Motion 120–200ms ease-out, none for `prefers-reduced-motion`.
- Desktop sidebar **220–232px**, main header **63–64px**, panel gutter **16px**, page margin **28–30px**. No massive empty canvas, no unrelated KPI tiles. Keep scroll independently in long lists and record panels; preserve focus/scroll when updating.
- Desktop `Offres` at >=1280px: **split view** with offer list (`minmax(0,1fr)`) left and selected record **~404–440px** right. Rows ~68–72px in Focus view, with current dense/comfortable mode preserved as a user setting. One strongly marked selected row, not all rows colored.
- Tablet: avoid forced 2 panels if either would become unusably narrow. Selected offer becomes drawer (overlay or full-width route) without losing list state.
- Mobile: native-feeling bottom tabbar, fixed app top bar; offer list single-column; record is full-screen, back button restores scroll/filter/focus. Minimum 44x44 tap targets. Tri actions above tabbar and safe-area.
- Navigation: keep **Tri, Offres, Candidatures, Leads, Exécutions**. Their existing hashes, counts, palette and keyboard shortcuts must still work. Other links may be visual affordances only if backed by real existing behavior; do not invent new features.

## Screen-by-screen blueprint

### A. Offres — Desktop (`01-offres-1440x900.png`) — highest priority

- Heading: succinct functional message, not buzzword dashboard KPI theatre. Summary derives from data. Search immediately visible; accessible filters and the original options (section, department, source/ATS company, status, IA, score, sort) all work and remain discoverable (secondary controls can live in popover/drawer).
- List: company monogram/logo substitute only when legitimate, title line, company/location/contract line, score and textual band. Selected row uses a discreet 3px violet left edge and faint violet surface. Scores/labels from application data; no invented `91` on real offer.
- Keyboard: j/k selection, x dismiss, s keep, a application sent, Enter external offer, Space expanded explanation, o record, / search, ? help; preserve original semantics, prevent shortcuts while focused in text fields.
- Right record: title, company/location/contract/age, real score, why ledger (positive/negative weights and explicit unknown/experience gate), source quote when available; warnings based on actual data only. Sticky footer with genuine existing actions (open offer, keep, initiate tracked process when supported). No forced extra network request.
- State handling: empty, filtered empty, pending, loading, error, tracking disabled, AI unknown, no eligible offers, selected item removed, switching filters, deep-link `?fiche`.

### B. Candidatures — Desktop (`02-candidatures-1440x900.png`)

- 4-column layout shown is a *visual arrangement only*. Actual statuses, columns and permitted transitions **must** come from current data and code, not invented by mockup. Horizontal scroll if real columns exceed space, or adaptive board; no card clipping.
- Cards: title, employer, stage, last interaction, next action/follow-up; one primary message per card. Due items get a small status chip and an unobtrusive summary bar, not a huge red banner. Existing table toggle, inbox, notes, documents, downloads, regeneration, action kit and application features remain complete.
- Preserve user edits, optimistic updates and rollback/error notifications. Do not change Worker API semantics.

### C. Tri — Mobile (`04-tri-390x844.png`) and desktop

- On mobile, a meaningful full-width card and progress over the active batch; 91/100 is sample data only. Score ledger and actual offer quote. Acknowledge unknown experience with explicit “Non précisée”. Actions **Écarter / Annuler / Garder** pinned above navigation, keyboard and swipe/touch mechanisms preserved where existing, no false actions.
- On desktop, **center the card but size it meaningfully (~680–760px)** rather than a tiny card on an empty expanse; use surrounding space deliberately (not blank dark wallpaper).

### D. Offres — Mobile list and record (`03-offres-390x844.png`, `05-fiche-390x844.png`)

- List/search/tabs readable at 390px, no horizontal scroll. Selected record fills the usable width with real score explanation and real actions; back restores state; no inaccessible offscreen controls. Respect bottom navigation and device safe-area.

### E. Leads / Exécutions — polish without feature removal

- Use same typography, panel surface, tables, state badges and clean empty states. Leads stay **funding signals, NEVER jobs**. Runs are observational: show status and measured counts without invented metrics. Maintain export/filter/action functionality and role-based error states. Do not create additional workflows.

## Nonnegotiable engineering guards

- Existing stack: **static HTML/CSS/vanilla JS in `src/job_match/dashboard/assets/`**, Python renderer, Cloudflare Worker as-is. No React/Next/Vite/Tailwind/shadcn, API rewrite, database migration, or extra services for an aesthetic refactor. Do not move personal data to client logs or public screenshots.
- Keep CSP hashes generated by `src/job_match/dashboard/render.py`; no new `unsafe-inline` JS, external fonts/CDNs or security relaxation. Keep Cloudflare Access boundary, offline-compatible static build and PWA manifest if applicable.
- Existing file responsibilities: `index.template.html`, `tokens.css`, `app.css`, `dashboard.css`; per-screen JS: `app.js`, `list.js`, `tri.js`, `board.js`, `leads.js`, `runs.js`, `why.js`, plus `score.js`, `palette.js`, `triage.js`, `tracking.js`, `ui.js`. Avoid a massive all-in-one rewrite; keep namespace `JM` consistency.
- Never use production CVs, contact details, real recruiter messages or private data in generated previews. Tests must use fixture/mocked data, and no live external API calls.
- Prioritize functionality and accessibility over literal pixel match. Do **not** delete a UI control merely because the static design sketch omits it; integrate it in a secondary accessible location.

## Acceptance requirements

1. All existing routes, major actions, keyboard shortcuts and errors still behave correctly; no console errors or silent API failures.
2. Offres split view at 1440, Candidatures usable at 1440, Tri and offers/list/record usable at 390, tablet adaptation at 768 and 1024.
3. No horizontal body overflow at 390px, no overlapping sticky nav/actions, min 44px touch targets, visible focus rings, accessible text, reduced motion, light mode intact.
4. Screenshot actual app using fixture data and Playwright at named resolutions, visually compare with references and iterate at least twice. App may differ in content but should match composition, density, hierarchy, surfaces and interactions.
5. Run project lint/test commands and document outcomes, including skipped tests and pre-existing failures. No fake green report.
6. Commit only task changes to a dedicated branch and push that branch only if Git remote and authentication work; never deploy, merge, push to `main`, force-push, use real production APIs or expose secrets.

## Intentional reference limitations

The images include a demo sidebar shortcut, invented employer examples and illustrative labels. They are **not** authorization to add data-model features, counts or made-up status transitions. Their content is fake; their layout is the requirement. The production UI is a complete responsive product, not a screenshot embedded in the app.
