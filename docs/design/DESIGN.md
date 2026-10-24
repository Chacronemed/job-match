---
version: 2.0
name: job-match-design
description: "The job-match dashboard, one system. It has Linear's density, Attio's records, Vercel's states and Raycast's keyboard care, without copying any brand. Dark only for now. Radix slate sits on three very close surface levels, with violet as the single accent and status hues only on dots and score marks. Inter Variable is self-hosted, the UI is set at 13 px and figures are tabular. Lucide icons are 16 px with a 1.5 stroke. Motion runs 120 to 200 ms ease-out on state changes, and all of it turns off under reduced motion."
colors:
  bg: "#111113"        # Radix slate-1: canvas, sidebar
  surface: "#18191b"   # slate-2: content, record panel
  raised: "#212225"    # slate-3: cards, group headers, menus
  ink: "#edeef0"       # slate-12
  ink-2: "#b0b4ba"     # slate-11
  ink-3: "#91959e"     # AA on every surface up to slate-4
  accent: "#6e56cf"    # violet-9
  accent-ink: "#baa7ff"  # violet-11
  line: "rgba(255,255,255,0.06)"
  line-2: "rgba(255,255,255,0.08)"
  line-3: "rgba(255,255,255,0.10)"
  strong: "#30a46c"    # green-9 (green-11 #3dd68c for words)
  stretch: "#ffc53d"   # amber-9 (amber-11 #ffca16 for words)
  danger: "#e5484d"    # red-9 (red-11 #ff9592 for words)
  info: "#0090ff"      # blue-9
typography:
  family: "Inter Variable (self-hosted, OFL), system-ui fallback"
  sizes: { xs: 11, sm: 12, ui: 13, md: 15, lg: 18, xl: 20 }
  tracking-titles: "-0.015em to -0.02em"
  numerals: tabular
space: { unit: 4, row: 40, nav-row: 30, head: 48, panel: 440, sidebar: 232 }
radius: { sm: 6, md: 8, lg: 12 }
motion: { fast: 120ms, base: 160ms, slow: 200ms, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }
---

# job-match dashboard design system

The source of truth for the dashboard (`src/job_match/dashboard/assets/`). The code mirrors it:
`tokens.css` holds the values below, `app.css` the components, and `ui.js`, `score.js` and
`palette.js` the shared behaviour. The system came out of prototype C (2026-10-22), which was
built from public captures of Linear, Attio, Vercel and Raycast. Each one gave one thing:

| Reference | What it gives | Where |
|---|---|---|
| Linear | navigation, dense lists, grouping, J/K | sidebar, lists, group headers |
| Attio | the record: editable properties, history, pipeline | record panel, Candidatures board |
| Vercel | system states: a dot plus a word, tabular durations, tinted error lines | Exécutions, banners |
| Raycast | component care, keyboard hints, the command palette | palette, `kbd`, the Tri action bar |

## Principles

1. **Density comes from rhythm, not from squeezing.** Rows are 40 px on a 4 px grid, with plenty of space around blocks and none wasted inside rows.
2. **Colour is data.** Chrome stays slate. Violet marks the accent: selection, the primary action, focus. Green, amber, red and blue appear only on a dot, a score mark or the few words that carry a state.
3. **One memorable moment.** When a Tri card arrives, its « Relevé du score » runs in: the lines come in one after the other and the total counts up. Everything else stays quiet.
4. **Every action has a key.** A view, a status and a decision can each be reached from the keyboard (see Keyboard). The palette reaches all of them.
5. **Nothing is invented.** A number on screen comes from the data. An unknown value says it is unknown ("Années non précisées", "—").

## Colour

Surfaces have three very close levels, 2 to 4 % apart in brightness: `--bg` (canvas, sidebar), `--surface` (content and record panel, inset with a 1 px line and a 12 px radius) and `--raised` (cards, group headers, menus).

- **Hover and active.** These are overlays, `--hover` at 4 % and `--active` at 8 % white, so they work on any level. There are no gradients anywhere.
- **Borders.** All of them are 1 px semi-transparent white: `--line` at 6 % (row separators), `--line-2` at 8 % (controls, cards) and `--line-3` at 10 % (overlays, hover on controls).
- **Shadows.** There is one soft shadow, `--overlay-shadow`, and it is used only on what floats: the palette, menus, the toast, and the overlay record panel below 1280 px.
- **Text.** It uses three greys only: `--ink` (titles, values), `--ink-2` (secondary text, labels) and `--ink-3` (metadata, counts, placeholders).

Contrast (WCAG AA, 4.5:1 for text), measured on the surfaces each ink is used on:

| Ink | on bg | on surface | on raised | on slate-4 |
|---|---|---|---|---|
| ink-2 | 9.1 | 8.5 | 7.6 | 6.9 |
| ink-3 | 6.3 | 5.9 | 5.3 | 4.8 |
| accent-ink | 9.0 | 8.4 | 7.6 | 6.9 |
| green-11 / amber-11 / red-11 | ≥ 8.9 | ≥ 8.3 | ≥ 7.5 | ≥ 6.8 |
| white on accent | 5.4 | | | |

Statuses are always a dot plus a word, never the colour alone:

| Status | Dot |
|---|---|
| À examiner | ink-3 |
| À candidater | slate-10 |
| Candidature envoyée | blue-9 |
| Entretien | green-9 |
| Refusée | red-9 |
| Ignorée | slate-7 |

Score bands follow the pipeline's own section (`data.py`): Forte in green-9, Éligible in the violet accent, À tenter in amber-9. Below the digest threshold an offer is Faible, in ink-3.

## Typography

- **Font.** Inter Variable, latin subset (48 KB), self-hosted under `fonts/`. The CSP allows it with `font-src 'self'`, and it is preloaded with `font-display: swap`. The fallback is `system-ui`.
- **Scale.** UI text is 13 px. Secondary text is 12 px, keyboard hints and ticks 11 px. A view title is 15 px semibold; the record and Tri card titles are 20 px semibold at -0.02em. Titles use `text-wrap: balance` and long words break (`overflow-wrap: anywhere`).
- **Figures.** Scores, counts, dates and durations are tabular (`.num`) and aligned right in columns.
- **French spacing.** Put a no-break space (U+00A0) inside « », before « : », « ? » and « ! », and between a number and its unit (`5 j`). Use the minus sign `−` for negative weights.
- **Copy.** French, sentence case, second person ("tu"), active verbs. A button says what happens ("Garder", "Voir mes candidatures"). An error says what to do next ("recharge la page"). An empty state invites the next step.

## Icons

Lucide icons (ISC) are 16 px with a 1.5 stroke and `currentColor`. They are always `aria-hidden`, since the control next to them carries the words.

- **Built in code.** The subset lives in `assets/lucide.js` as icon nodes and is built with `createElementNS`, so no SVG markup is parsed.
- **Adding one.** Add its name to `scripts/build_lucide.py` and run the script against a `lucide-static` package (the script's docstring has the steps).
- **Glyphs replaced by icons.** The arrows ← → and Enter ↵ are not in the Inter subset, so `kbd()` draws them as icons.

## Layout

```
≥ 1280 px                                       < 1280 px              ≤ 760 px
┌ sidebar 232 ┬ main (inset) ──────┬ record 440 ┐  record = overlay      no sidebar; tab bar 60 px
│ brand       │ view head 48       │ bar 48     │  (slides over, the     at the bottom (safe area)
│ Rechercher… │ ─────────────────  │ title      │  page behind is        record = full screen
│ Tri       58│ group header 36    │ properties │  inert)                toasts at the top
│ Candid.    3│ row 40             │ sections   │
│ …           │ row 40             │            │
│ snapshot  ? │                    │            │
└─────────────┴────────────────────┴────────────┘
```

- **Sidebar.** 232 px: the brand; the search button that opens the palette, with its `Ctrl K` / `⌘K` hint; and the views as real links (`href="#tri"`), so a modifier click opens a new tab. Each nav item is 30 px with a count. The footer holds the snapshot time (full date in the tooltip) and "Raccourcis".
- **Record panel.** It shares the screen at 1280 px and up, as a third grid column. Below that it covers the page.
- **Phone tab bar.** Five icons with labels. A badge shows the Tri count, and hides at zero.
- **Hash.** It carries the state: `#<view>?q=…&hide=…&dept=…&st=…&min=…&from=…&to=…&sort=…&fiche=<key>`. Old hashes still work (`today` → `tri`, `jobs` → `offres`, `runs` → `executions`).

## Counters

Every number in the sidebar, the tab bar and the view heads comes from one function, `triage.js sidebarCounts`. `worker/test/triage.test.mjs` checks the invariants.

| Counter | Definition |
|---|---|
| Tri | Listed offers still « À examiner » (untriaged) whose score is at or above `digest.min_score`; an offer with no score counts, its score is unknown, not low (`triageQueue`) |
| Candidatures | Tracked offers whose status is on the board (À candidater, Envoyée, Entretien, Refusée), listed or not (a closed offer still counts) |
| Offres | Listed rows: open offers within `jobs.max_age_days`; a group of postings counts once |
| Leads | Funding leads in the snapshot |
| Exécutions | Runs in the snapshot (the last 30) |

Invariants:
- **Tri ⊂ Offres.**
- **Tri + triaged offers at or above the digest = Offres at or above the digest.** An offer below the threshold stays in Offres and is never in the Tri.
- **Each decision takes exactly one offer out of the Tri.** « Garder » adds one to Candidatures; « Écarter » adds none; Offres doesn't change.

The Tri header (`N / total`) counts the session's queue, which is fixed when the Tri starts, so a card never moves under the finger. The sidebar's Tri count is live; the two agree until data reloads.

## Motion

Hover and focus are instant. Only state changes move, at 120 to 200 ms with `--ease` (expo out); nothing bounces.

| What | How |
|---|---|
| View change | View Transitions API: the old view fades out in 120 ms, the new one rises 6 px in 200 ms. Plain swap without the API |
| Record panel | At ≥ 1280 a View Transition: the main view's edge morphs and the panel slides in 40 px. Below 1280 it slides in from the right edge (200 ms) and slides out (160 ms) |
| Tri card | Follows the pointer (translate + a tilt of dx/16, at most 14°). Released past 110 px, or flicked (velocity over the last 90 ms > 0.45 px/ms), it leaves at that speed (140 to 300 ms). Otherwise it springs back (200 ms). The card underneath rises from `translateY(10px) scale(0.95)`. Undo flies the card back in from the side it left |
| « Relevé » | When a card arrives: the lines come in at 45 ms steps, the total counts up from the start, then the scale fills and the gap sentence fades in |
| Lists | Optimistic updates: the row moves to its new place with FLIP (`ui.js flip`), never a jump |
| Overlays | Palette and help: fade + scale 0.98 → 1 (160 ms); menus 120 ms; the toast slides up (from the top on phones) |
| Loading | Skeleton rows and cards pulse in opacity |

Under `prefers-reduced-motion: reduce`, everything above is off. The CSS durations drop to 0, the JS skips the Web Animations and the View Transitions, and the count-up shows the total at once. Dragging still follows the finger: that is direct manipulation, not an animation.

## Keyboard

| Keys | Action |
|---|---|
| `Ctrl/⌘ K` | Command palette: go to a view, search an offer, change the open record's status, actions |
| `?` | Shortcuts help |
| `G` then `T` / `C` / `O` / `L` / `E` | Tri, Candidatures, Offres, Leads, Exécutions |
| `Échap` | Close the record, the palette or the help (and the reason step in Tri) |
| Tri: `→` / `←` | Keep / drop |
| Tri: `Z` | Undo the last decision |
| Tri: `1`–`4` | Reason for the drop (off topic, too senior, missing skill, location) |
| Tri: `↵` | Open the card's record |
| Tri: `↑` `↓`, `Page ↑` `Page ↓`, `Space` | Scroll the card |

Every hint is a `kbd` chip, `aria-hidden`, and the control carries `aria-keyshortcuts`. The hints are hidden on coarse pointers.

## Components

**View head (48 px).** It holds the `h1` title, its count in ink-3, then the view's controls on the right. It is sticky.

**Tri card.** It sits on `--raised` with a 12 px radius. It is as tall as its content, up to the space above the bar, and its content scrolls inside it (`.tcard-scroll`, 20 px padding, 16 px on phones). The bar never moves. The card behind takes the same box and peeks out 10 px below, its text hidden. From top to bottom:
1. the badges (Nouveau, À tenter, N départements);
2. the **facts** (`dl`), label above value, two columns: Poste (the title across both, a button that opens the record), Entreprise, Expérience demandée, Lieu, Contrat, Salaire, Publiée (« Hier », « Il y a 3 j », the full date in the tooltip). Salaire appears only when the description has an explicit `Salaire :` / `Rémunération :` line, shown word for word; the data has no salary field;
3. the « Relevé du score », collapsible;
4. the **description**, whole (`description.js`):
   - the usual sections when the text names them (Missions, Le poste, Profil, Compétences, Avantages, Entreprise, Processus de recrutement), as 13 px semibold headings;
   - bullet lines become lists;
   - the rest stays paragraphs, with their line breaks (`white-space: pre-line`, line height 1.6);
5. « Voir l’offre ».

While dragging, the stamps "Garder" (green, left) and "Écarter" (red, right) appear. ↑ ↓, Page ↑ ↓ and Space scroll the card; ← → decide.

**Tri bar.** It is fixed at the bottom: Écarter, the undo icon button and Garder (primary). After a drop, the reason step sits **above** the buttons and never replaces them. It names the offer that just left (« Dernière offre écartée : … »), so it can't be read as being about the card on screen, and offers four chips (1–4) and "Passer". The next decision closes it without a reason. On phones the chips stay on one row that scrolls sideways.

**Progress.** The header reads `N / total restantes · lot X de Y` (`triage.js triProgress`): N is what is left in this batch, total what is left in the queue, and both shrink by one with each decision. X of Y is the batch. The 96 px bar fills with the batch (`scaleX`), with `aria-valuetext`. At a batch end the finished batch stays shown, full, until « Lot suivant ».

**« Relevé du score » (`ui.js ledger`, `score.js`).** The score adds up line by line, read from the scorer's own explanation lines:
- "Point de départ";
- each matched skill (+) and malus (−);
- the title bonus;
- Total, then a 0–100 scale with the « digest » and « forte » ticks from `data.thresholds`;
- one sentence: « Il manque N points pour forte. », « Forte : N points au-dessus du seuil. », or for À tenter, the years from the stretch line.

A capped score (0 or 100) has no start line, because the sum before the cap is not in the data.

On the Tri card it is **collapsible, closed by default**:
- **Closed:** one summary button reads score, band, sentence (`64 · Éligible · Il manque 11 points pour forte.`).
- **Open:** the lines, then the counters:
  - « N compétences de ton profil absentes de l’offre » (sans effet sur le score), which expands to the list;
  - « Dans l’offre, pas dans ton profil : … ».
- **State:** the open/closed choice is shared by every card and kept in `localStorage` (`jm.ledger.open.v1`, in try/catch, with a memory fallback).
- **Motion:** the cascade runs when it is open; the summary score counts up when it is closed.

The record panel shows it open, with no toggle.

**Record panel (Attio).** In the Tri it opens only on demand (a click on the title, or `↵`), never by itself: a decision closes it, and its key is not kept in the hash there. Opened from the Tri it leaves out the description, which the card already shows.

**Record panel, contents.** A bar holds the view name, "Voir l’offre" (icon) and Fermer (`Échap`). Below it come the title (20 px, focused on open), company and place, then a property list: icon + label in ink-3, value in ink-2, 32 px rows. The sections follow, in order: « Description de l’offre » (the same layout as the Tri card), ledger, « Pourquoi cette offre ? » (open), postings for a group, tracking (status, dates, CV, note, verdicts).

**Buttons.** All are 32 px (44 px on phones):
- `.button`: raised, line-2;
- `.button.primary`: accent, white text, one per screen;
- `.icon-btn`: 28 px (44 px on phones), always labelled;
- `.link-btn`: accent ink, no underline at rest.

**Pills and badges.** A `.pill` is a 24 px outlined tag (warning variant in amber). A `.badge` is a 22 px filled tag (accent soft, amber soft).

**kbd.** A 20 px chip on slate-4 with a line-2 border, 11 px medium.

**Toast.** It sits on slate-3 with a line-3 border and the overlay shadow, centred at the bottom (at the top on phones). Actions are link buttons. A question (the follow-up after « J’ai postulé ») holds the toast until answered and `Échap` dismisses it. Hovering or focusing it holds it too.

**Palette.** A `<dialog>` 640 px wide, 12vh from the top:
- a borderless 15 px search field;
- groups with 12 px titles;
- 40 px rows with an icon or dot, the label with its matches in accent ink, a hint in ink-3, and the score or keys on the right;
- a footer: « Ouvrir ↵ | Naviguer ↑↓ ».

Matching is word-based and accent-folded, words in any order.

**Help.** A `<dialog>` with three columns of key / action rows.

**Banners.** The tracking banner is amber (`track-banner`) and the pending-offline banner red (`tri-pending`). Each says what happened and what to do, with a retry button.

**Skeletons.** While tracking loads, skeleton rows and cards show in place of the content.

## Accessibility

- **Focus.** Visible focus is a 2 px violet-10 outline with a 2 px offset (`:focus-visible`). The record title takes focus when the panel opens and shows no ring, since it is not a control. Sticky heads leave room through `scroll-padding`.
- **Overlay record.** Below 1280 px, `main`, the sidebar and the tab bar are `inert` while the record is open, and closing it gives focus back to what opened it.
- **Live regions.** The toast and `tri-live` are polite live regions.
- **Targets.** Every control is at least 44 px below 768 px.
- **Content safety.** Every string from the data reaches the DOM through `textContent`; the scripts never parse HTML.

## Light mode

Light mode is planned, not shipped. `applyTheme` is kept but forces dark (`DARK_ONLY`), the `#theme-toggle` button stays in the page but `hidden`, and `theme-color` follows the applied theme. When light mode comes back, it needs its own measured inks: the old light accent failed AA (AUDIT P1-6).

## Migration status (phase 3)

The views move to this system one at a time. Done: the shell (sidebar, tab bar, palette, help, record panel, toast) and **Tri**. Still legacy: Candidatures, Offres, Leads and Exécutions. They keep `dashboard.css`, whose tokens are remapped onto `tokens.css` so the legacy views share the colours. That file is deleted with the last view.

## Do and don't

**Do:**
- Use a dot plus a word for a state.
- Use one primary button per screen.
- Use tabular figures.
- Give every action a key and list it in the palette.
- Say what is unknown.
- Animate transform and opacity only.

**Don't:**
- Use gradients, decorative backgrounds or shadows on rows.
- Use a second accent.
- Use colour on neutral text.
- Use all-caps eyebrows.
- Use "A · B · C" meta strings where properties fit.
- Use monospace for labels.
- Animate hover.
- Put content behind a gesture with no button or key.
