---
version: alpha
name: job-match-design
description: "The job-match dashboard system: a near-black canvas (#010102), light gray text (#f7f8f8) and one lavender-blue accent (#5e6ad2) used for focus, the active tab and link emphasis. Dense, technical, quiet. Type is the system sans at 400-600; data tokens (scores, years, counts) are set in the system mono. Panels are charcoal (#0f1011) with hairline borders. Two semantic data colours only: green for a strong match, amber for a stretch job. Light mode is the inverse of the same ladder."

colors:
  primary: "#5e6ad2"
  on-primary: "#ffffff"
  primary-hover: "#828fff"
  primary-focus: "#5e69d1"
  ink: "#f7f8f8"
  ink-muted: "#d0d6e0"
  ink-subtle: "#8a8f98"
  ink-tertiary: "#62666d"
  canvas: "#010102"
  surface-1: "#0f1011"
  surface-2: "#141516"
  surface-3: "#18191a"
  surface-4: "#191a1b"
  hairline: "#23252a"
  hairline-strong: "#34343a"
  hairline-tertiary: "#3e3e44"
  inverse-canvas: "#ffffff"
  inverse-surface-1: "#f5f6f6"
  inverse-surface-2: "#f6f7f7"
  inverse-ink: "#000000"
  brand-secure: "#7a7fad"
  semantic-success: "#27a644"
  semantic-stretch: "#c9962b"
  semantic-overlay: "#000000"

typography:
  display-xl:
    fontFamily: System Sans
    fontSize: 80px
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: -3.0px
  display-lg:
    fontFamily: System Sans
    fontSize: 56px
    fontWeight: 600
    lineHeight: 1.10
    letterSpacing: -1.8px
  display-md:
    fontFamily: System Sans
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -1.0px
  headline:
    fontFamily: System Sans
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.20
    letterSpacing: -0.6px
  card-title:
    fontFamily: System Sans
    fontSize: 22px
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: -0.4px
  subhead:
    fontFamily: System Sans
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.40
    letterSpacing: -0.2px
  body-lg:
    fontFamily: System Sans
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.50
    letterSpacing: -0.1px
  body:
    fontFamily: System Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.50
    letterSpacing: -0.05px
  body-sm:
    fontFamily: System Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.50
    letterSpacing: 0
  caption:
    fontFamily: System Sans
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.40
    letterSpacing: 0
  button:
    fontFamily: System Sans
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.20
    letterSpacing: 0
  eyebrow:
    fontFamily: System Sans
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.30
    letterSpacing: 0.4px
  mono:
    fontFamily: System Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.50
    letterSpacing: 0

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  xxl: 24px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 96px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 14px
  button-primary-pressed:
    backgroundColor: "{colors.primary-focus}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
  button-secondary:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 14px
  button-tertiary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 14px
  button-inverse:
    backgroundColor: "{colors.inverse-canvas}"
    textColor: "{colors.inverse-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 14px
  pricing-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  pricing-card-featured:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  feature-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  product-screenshot-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    padding: 24px
  testimonial-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body-lg}"
    rounded: "{rounded.lg}"
    padding: 32px
  customer-logo-tile:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-subtle}"
    typography: "{typography.caption}"
    rounded: "{rounded.xs}"
    padding: 16px
  text-input:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  text-input-focused:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  pricing-tab-default:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-subtle}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: 6px 14px
  pricing-tab-selected:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: 6px 14px
  cta-banner:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.headline}"
    rounded: "{rounded.lg}"
    padding: 48px
  changelog-row:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.xs}"
    padding: 24px 0
  status-badge:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: 2px 8px
  top-nav:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.xs}"
    height: 56px
  footer:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-subtle}"
    typography: "{typography.caption}"
    rounded: "{rounded.xs}"
    padding: 64px 32px
---

## Overview

The job-match canvas is near-black — `{colors.canvas}` is #010102, essentially pure black with a faint blue tint. On top sits a four-step surface ladder (`{colors.surface-1}` through `{colors.surface-4}`) for cards, panels, and lifted tiles, with hairline borders running from `{colors.hairline}` (#23252a) up through `{colors.hairline-strong}` and `{colors.hairline-tertiary}`. Light gray text (`{colors.ink}` #f7f8f8) carries the body and headlines.

The single chromatic accent is **lavender-blue** `{colors.primary}` (#5e6ad2) — used on the focus ring, the active tab, link emphasis and the rare primary button. A lighter hover state (`{colors.primary-hover}` #828fff) and a focus-tinted variant (`{colors.primary-focus}` #5e69d1) extend the same hue. No other chromatic colour on chrome. The data needs two semantic colours and gets exactly two: `{colors.semantic-success}` (#27a644) marks a strong match, `{colors.semantic-stretch}` (#c9962b) marks a stretch job; eligible-but-not-strong uses the accent.

Type runs the system sans (`-apple-system, Segoe UI, Roboto, Inter`) at weight 400–600; nothing is downloaded, the page works offline. The mono stack (`ui-monospace, JetBrains Mono, Menlo`) is reserved for data tokens: scores, years, counts, ids.

The page rhythm is **dense data**: a 56px top bar, a tab row, a compact KPI strip, a filter panel and a 36px-row table, each lifted onto `{colors.surface-1}` with `{rounded.lg}` 12px corners. The chrome is minimal so the rows do the work.

**Key Characteristics:**
- **Dark-canvas data system** — `{colors.canvas}` (#010102), near-black with a faint blue tint.
- **Lavender-blue accent** (`{colors.primary}` #5e6ad2) — used scarcely: focus ring, active tab, link emphasis.
- Four-step surface ladder (canvas → surface-1 → surface-2 → surface-3 → surface-4) carries hierarchy without shadow.
- Display tracking pulls aggressively negative (-3.0px at 80px); body holds at -0.05px.
- Cards use `{rounded.lg}` 12px corners with 1px hairline borders — never pill, rarely 16px.
- **Data tables** dominate the page; the chrome is a dark frame for the rows.
- Two semantic data colours (strong, stretch), nothing else. No gradients. No shadows at rest.

## Colors

### Brand & Accent
- **Lavender-Blue** ({colors.primary}): The single accent — focus ring, active tab, link emphasis, primary button.
- **Lavender Hover** ({colors.primary-hover}): Lighter lavender (#828fff) — hovered state of the primary CTA.
- **Lavender Focus** ({colors.primary-focus}): Focus-ring tint (#5e69d1) — focused inputs, focused buttons.
- **Brand Secure** ({colors.brand-secure}): Muted lavender-gray (#7a7fad) — reserved; unused on the dashboard.

### Surface
- **Canvas** ({colors.canvas}): Default page background — #010102, near-pure black with a faint blue tint.
- **Surface 1** ({colors.surface-1}): One step above canvas — feature cards, pricing cards, product screenshot panels.
- **Surface 2** ({colors.surface-2}): Two steps above — featured pricing card, hovered cards.
- **Surface 3** ({colors.surface-3}): Three steps above — line-tertiary backgrounds, sub-nav.
- **Surface 4** ({colors.surface-4}): Four steps above — bg-level-3, deepest lifted surface.
- **Hairline** ({colors.hairline}): 1px borders on cards and dividers.
- **Hairline Strong** ({colors.hairline-strong}): Stronger 1px borders — input focus rings.
- **Hairline Tertiary** ({colors.hairline-tertiary}): Tertiary borders for nested surfaces.
- **Inverse Canvas** ({colors.inverse-canvas}): Pure white — surface of the inverse pill CTA on a small set of section openers.
- **Inverse Surface 1** ({colors.inverse-surface-1}): One step above inverse canvas.
- **Inverse Surface 2** ({colors.inverse-surface-2}): Two steps above inverse canvas.

### Text
- **Ink** ({colors.ink}): All headlines and emphasized body type — light gray #f7f8f8.
- **Ink Muted** ({colors.ink-muted}): Secondary type at #d0d6e0 — meta info on hero panels.
- **Ink Subtle** ({colors.ink-subtle}): Tertiary type at #8a8f98 — deselected pricing tabs, footer columns.
- **Ink Tertiary** ({colors.ink-tertiary}): Quaternary at #62666d — disabled, footnotes.

### Semantic
- **Success Green** ({colors.semantic-success}): a strong match — the KPI figure, the row dot, the score bar, the funnel segment.
- **Stretch Amber** ({colors.semantic-stretch}): a stretch job (one year of experience short) — the same four places.
- **Overlay** ({colors.semantic-overlay}): Pure black overlay scrim for modals.

## Typography

### Font Family

- **System Sans** — `-apple-system, BlinkMacSystemFont, Segoe UI, Inter, Roboto, Helvetica Neue, Arial`. One family for every size; nothing is downloaded.
- **System Mono** — `ui-monospace, JetBrains Mono, SF Mono, Menlo, Consolas`. Scores, years, counts, ids and the KPI figures.

One voice from the wordmark to the captions; only the data tokens change family.

### Hierarchy

| Token | Size | Weight | Line Height | Letter Spacing | Use |
|---|---|---|---|---|---|
| `{typography.display-xl}` | 80px | 600 | 1.05 | -3.0px | Largest hero headline |
| `{typography.display-lg}` | 56px | 600 | 1.10 | -1.8px | Section opener headlines |
| `{typography.display-md}` | 40px | 600 | 1.15 | -1.0px | Sub-section headlines |
| `{typography.headline}` | 28px | 600 | 1.20 | -0.6px | Pricing tier titles, CTA banner heading |
| `{typography.card-title}` | 22px | 500 | 1.25 | -0.4px | Feature card title |
| `{typography.subhead}` | 20px | 400 | 1.40 | -0.2px | Lead body, intro paragraphs |
| `{typography.body-lg}` | 18px | 400 | 1.50 | -0.1px | Hero subhead, lead paragraphs |
| `{typography.body}` | 16px | 400 | 1.50 | -0.05px | Default body |
| `{typography.body-sm}` | 14px | 400 | 1.50 | 0 | Card body, footer columns |
| `{typography.caption}` | 12px | 400 | 1.40 | 0 | Captions, meta, status |
| `{typography.button}` | 14px | 500 | 1.20 | 0 | All button labels |
| `{typography.eyebrow}` | 13px | 500 | 1.30 | 0.4px | Section eyebrow (slight positive tracking) |
| `{typography.mono}` | 13px | 400 | 1.50 | 0 | Scores, years, counts, ids |

### Principles

- **Aggressive negative tracking on display** (-3.0px at 80px ≈ 4% of size).
- **Single voice from display to body.** Display-xl at 600 → body at 400 — same family, narrower weights.
- **Eyebrow uses positive tracking** (+0.4px) — contrast against the negative-tracked display marks the eyebrow as taxonomy.
- **Mono only for data tokens.** Scores, years, counts and ids; never a label, never a heading.

### Note on Font Substitutes

No proprietary typeface. The dashboard must open offline from a file, so the stacks above are system fonts only; **Inter** or **Geist Sans** are the free substitutes if a webfont is ever acceptable.

## Layout

### Spacing System

- **Base unit**: 4px.
- **Tokens (front matter)**: `{spacing.xxs}` 4px · `{spacing.xs}` 8px · `{spacing.sm}` 12px · `{spacing.md}` 16px · `{spacing.lg}` 24px · `{spacing.xl}` 32px · `{spacing.xxl}` 48px · `{spacing.section}` 96px.
- Card interior padding: `{spacing.lg}` 24px on feature/pricing cards; `{spacing.xl}` 32px on testimonial cards; `{spacing.xxl}` 48px on CTA banners.
- Pill button padding: 8px vertical · 14px horizontal (compact button spec).
- Form input padding: 8px vertical · 12px horizontal.

### Grid & Container

- Max content width sits around 1280px.
- Card grids are 3-up at desktop, 2-up at tablet, 1-up at mobile.
- Pricing tier grid is 3-up; comparison strip below shows checkmarks per tier.
- Product screenshot panels span full content width — they're the protagonist.

### Whitespace Philosophy

The dark canvas IS the whitespace. Sections separate by lift onto surface-1 panels, not by gaps in white. Within a panel, generous `{spacing.lg}` 24px gaps between content blocks; `{spacing.section}` 96px between sections.

## Elevation & Depth

| Level | Treatment | Use |
|---|---|---|
| 0 (flat) | No shadow, no border | Default for body type, hero text, footer |
| 1 (charcoal lift) | `{colors.surface-1}` background on canvas, 1px `{colors.hairline}` | Default cards, product panels |
| 2 (surface-2 lift) | `{colors.surface-2}` background, 1px `{colors.hairline-strong}` | Featured pricing card, hovered cards |
| 3 (surface-3 lift) | `{colors.surface-3}` background | Sub-nav, dropdown menus |
| 4 (focus ring) | 2px `{colors.primary-focus}` outline at 50% opacity | Focused input, focused button |

Depth is carried by the surface ladder + hairline borders. No drop shadows on dark.

### Decorative Depth

- **No atmospheric gradients, no spotlight cards.**
- **Subtle white edge highlight** on the top edge of lifted panels — gives the dark surface a faint "pixel rendered" feel.

## Shapes

### Border Radius Scale

| Token | Value | Use |
|---|---|---|
| `{rounded.xs}` | 4px | Small chips, status badges |
| `{rounded.sm}` | 6px | Inline tags |
| `{rounded.md}` | 8px | All buttons, form inputs |
| `{rounded.lg}` | 12px | Pricing cards, feature cards, testimonial cards |
| `{rounded.xl}` | 16px | Product screenshot panels |
| `{rounded.xxl}` | 24px | Oversized CTA banners (rare) |
| `{rounded.pill}` | 9999px | Pricing tab toggles, status pills |
| `{rounded.full}` | 9999px | Avatar circles |

### Photography & Illustration Geometry

- Product UI screenshots dominate; they sit in `{rounded.xl}` 16px tiles with `{spacing.lg}` 24px outer padding.
- Customer logo tiles render at small sizes (~24px logo height) on `{colors.canvas}` with no border.
- Avatar circles in testimonial cards use `{rounded.full}` at 32–40px sizes.

## Components

### Buttons

**`button-primary`** — Lavender CTA. The default primary CTA across all pages.
- Background `{colors.primary}`, text `{colors.on-primary}`, type `{typography.button}`, padding 8px 14px, rounded `{rounded.md}`.
- Pressed state lives in `button-primary-pressed` (background shifts to `{colors.primary-focus}`).
- Hover state lives in `button-primary-hover` (background shifts to `{colors.primary-hover}` lighter lavender).

**`button-secondary`** — Charcoal button. Used for secondary CTAs ("Sign in", "Read changelog").
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.button}`, padding 8px 14px, rounded `{rounded.md}`. 1px `{colors.hairline}` border.

**`button-tertiary`** — Plain text button.
- Background `{colors.canvas}`, text `{colors.ink}`, type `{typography.button}`, rounded `{rounded.md}`, padding 8px 14px.

**`button-inverse`** — White-on-dark inverse CTA.
- Background `{colors.inverse-canvas}`, text `{colors.inverse-ink}`, type `{typography.button}`, rounded `{rounded.md}`, padding 8px 14px.

### Pricing Tabs

**`pricing-tab-default`** + **`pricing-tab-selected`** — Pill-toggle on `/pricing`.
- Default: `{colors.canvas}` background, `{colors.ink-subtle}` text, rounded `{rounded.pill}`, padding 6px 14px.
- Selected: `{colors.surface-2}` background, `{colors.ink}` text — selected = surface lift.

### Cards & Containers

**`pricing-card`** — Each tier on `/pricing`.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.body}`, rounded `{rounded.lg}`, padding 24px. 1px `{colors.hairline}` border.

**`pricing-card-featured`** — Recommended tier — surface lift to surface-2.
- Background `{colors.surface-2}`, otherwise identical structure.

**`feature-card`** — Generic feature highlight tile.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.body}`, rounded `{rounded.lg}`, padding 24px.

**`product-screenshot-card`** — The dominant card type — frames a screenshot.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.body}`, rounded `{rounded.xl}`, padding 24px.

**`testimonial-card`** — Customer quote with avatar + name + role.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.body-lg}`, rounded `{rounded.lg}`, padding 32px.

**`customer-logo-tile`** — Small tile in the customer marquee.
- Background `{colors.canvas}`, text `{colors.ink-subtle}`, type `{typography.caption}`, rounded `{rounded.xs}`, padding 16px.

**`cta-banner`** — Closing CTA panel near page bottom.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.headline}`, rounded `{rounded.lg}`, padding 48px.

### Inputs & Forms

**`text-input`** + **`text-input-focused`** — Form fields on `/contact/sales` and signup overlays.
- Background `{colors.surface-1}`, text `{colors.ink}`, type `{typography.body}`, rounded `{rounded.md}`, padding 8px 12px.
- Focused state retains the same surface; the focus ring is a 2px `{colors.primary-focus}` outline at 50% opacity.

### Status & Build Page

**`changelog-row`** — Each row in `/build` (changelog page) listing version, date, and changes.
- Background `{colors.canvas}`, text `{colors.ink}`, type `{typography.body}`, rounded `{rounded.xs}`, padding 24px 0. 1px `{colors.hairline}` bottom rule.

**`status-badge`** — Small status pill.
- Background `{colors.surface-2}`, text `{colors.ink-muted}`, type `{typography.caption}`, rounded `{rounded.pill}`, padding 2px 8px.

### Navigation

**`top-nav`** — Sticky dark bar with the job-match wordmark left, the tab row next to it, and a `button-secondary` ("Sign in") + `button-primary` ("Get started") pair right.
- Background `{colors.canvas}`, text `{colors.ink}`, type `{typography.body-sm}`, height 56px.

### Footer

**`footer`** — Dense link grid on `{colors.canvas}` with the job-match wordmark left (unused on the dashboard).
- Background `{colors.canvas}`, text `{colors.ink-subtle}`, type `{typography.caption}`, padding 64px 32px.

## Do's and Don'ts

### Do

- Reserve `{colors.canvas}` (#010102) as the system's anchor surface — the faint blue tint is intentional.
- Use `{colors.primary}` lavender ONLY for: brand mark, primary CTA, focus ring, link emphasis.
- Use the four-step surface ladder for hierarchy. Avoid skipping levels.
- Pair display weight 600 with body weight 400 — the system resists 700+ display weights.
- Apply negative letter-spacing aggressively on display.
- Let the rows be the protagonist: compact, aligned, tabular figures.
- Compose CTAs as `{rounded.md}` 8px corners.

### Don't

- Don't invent a third data colour: strong is green, stretch is amber, everything else is the accent or ink.
- Don't use lavender as a section background or card fill.
- Don't introduce a second chromatic accent (orange, pink, green for marketing).
- Don't add atmospheric gradients or spotlight cards.
- Don't pill-round CTAs.
- Don't use `#000000` true black as the canvas.
- Don't combine multiple bright accents in product screenshot mockups.

## Responsive Behavior

### Breakpoints

| Name | Width | Key Changes |
|---|---|---|
| Desktop-XL | 1440px | Default desktop layout |
| Desktop | 1280px | Card grid 3-up maintained |
| Tablet | 1024px | Card grid 3-up → 2-up |
| Mobile-Lg | 768px | Pricing comparison becomes accordion; nav hamburger |
| Mobile | 480px | Single-column; display-xl scales 80px → ~36px |

### Touch Targets

- CTAs hold ≥40px tap height across viewports.
- Pricing tab pills hold ≥36px tap height; touch viewports grow to ≥44px.
- Form inputs hold ≥44px tap target on touch.

### Collapsing Strategy

- **Top nav**: links collapse to hamburger below 768px.
- **Card grids**: 3-up → 2-up at 1024px → 1-up below 768px.
- **Pricing comparison**: per-tier accordion below 768px.
- **Display type**: `{typography.display-xl}` 80px scales toward `{typography.display-md}` 40px on mobile.

### Image Behavior

- Product UI screenshots maintain aspect ratio and never crop.
- Customer logos in the marquee may collapse from 6-up to 3-up below 768px.

## Iteration Guide

1. Focus on ONE component at a time and reference it by its `components:` token name.
2. When introducing a section, decide first which surface lift it lives on.
3. Default body to `{typography.body}` at weight 400.
4. Run `npx @google/design.md lint DESIGN.md` after edits.
5. Add new variants as separate component entries.
6. Treat lavender as scarce: brand mark, primary CTA, focus, link emphasis.
7. Lead every section with a product UI screenshot.

## Known Gaps

- Form-field error and validation styling is not visible on the inspected pages.
- Form-field error styling: defined for the dashboard's tracking form (see `track-form` below).

## Light Mode

Light mode is the inverse of the same ladder, chosen by `prefers-color-scheme` and overridable
with the toggle (`data-theme` on `<html>`, remembered per browser). Only the surface and ink
roles change; the accent and the two data colours keep their hue and get darker inks for
contrast on white.

| Role | Dark | Light |
|---|---|---|
| canvas | `#010102` | `{colors.inverse-canvas}` #ffffff |
| surface-1 / 2 / 3 | `#0f1011` / `#141516` / `#18191a` | `{colors.inverse-surface-1}` #f5f6f6 / #eef0f1 / #e6e8ea |
| hairline / strong | `#23252a` / `#34343a` | #e3e5e8 / #cfd2d6 |
| ink / muted / subtle | `#f7f8f8` / `#d0d6e0` / `#8a8f98` | `{colors.inverse-ink}` #000000 / #2f3237 / #5f646c |
| success ink | #4fc96a | #1f8a39 |
| stretch ink | #e0b254 | #8a6512 |

## Dashboard Components

The components the dashboard page actually uses (`src/job_match/dashboard/assets/`).

- **`top-bar`** — 56px, `{colors.canvas}`, 1px `{colors.hairline}` bottom rule, sticky. Wordmark (16px, 600, -0.3px) left, snapshot time in `{colors.ink-subtle}` caption, tab row, theme toggle (`button-secondary`) right.
- **`tab`** — text button, 44px tall, `{colors.ink-subtle}` at rest, `{colors.ink}` selected with a 2px `{colors.primary}` underline. The count after the label is mono caption in `{colors.ink-tertiary}`.
- **`kpi-tile`** — `{colors.surface-1}`, 1px hairline, `{rounded.lg}`, 10px 14px. Caption label, 24px mono figure; the figure takes the section colour (success for strong, stretch for stretch).
- **`filter-panel`** — `{colors.surface-1}` panel holding the controls on one grid row; collapses into a `<details>` under 768px. Inputs are `text-input` on `{colors.canvas}` with a `{colors.hairline-strong}` border, 36px tall.
- **`section-chip`** — pill toggle (`pricing-tab`), 36px, dot in the section colour when pressed, `{colors.surface-2}` fill when pressed.
- **`table-row`** — 36px, 13px, 1px `{colors.hairline}` rule, `{colors.surface-2}` on hover and when expanded. The first cell is a button that opens the details row; a dot in the section colour precedes the title. Score is a 44px bar + mono figure; years and counts are mono. Job tables use a fixed layout: Score, Years, Posted, Age, Dept, Contract, Status and Link have fixed widths sized for their longest value, with tabular figures, and never clip. Title and Company share the rest, ellipsize, and show the full text as a tooltip. Dates are short ("19/10") with the full date as a tooltip; the details row shows full dates. Under 768px a row becomes a two-column card with inline labels.
- **`details-row`** — `{colors.surface-1}` with a `{colors.hairline-strong}` bottom rule: `track-form`, meta caption, the stretch note in stretch ink, then the `why-panel`.
- **`funnel-bar`** — 16px, `{rounded.xs}`, segments rejected (#3e3e44 dark / #c7cacf light), duplicates (`{colors.ink-tertiary}`), eligible (`{colors.primary}`) with the strong share inside it (`{colors.semantic-success}`), stretch (`{colors.semantic-stretch}`); widths are shares of fetched.
- **`run-card`** — `{colors.surface-1}`, `{rounded.lg}`, 12px 16px: date (500), `status-badge` for a reprocess run, fetched count right, the funnel, then the stats line and the rejection reasons in caption size with mono figures.
- **`status-badge` (tracking)**: pill, 12px, weight 500. Each status has its own colours:
  - *to review*: `{colors.surface-2}` fill, `{colors.ink-subtle}` text.
  - *to apply*: `primary-soft` fill, link ink.
  - *applied*: `success-soft` fill, success ink.
  - *interview*: solid `{colors.semantic-success}` fill, white text.
  - *rejected*: `danger-soft` fill, danger ink (#f2777a dark / #b3261e light).
  - *ignored*: no fill, `{colors.ink-subtle}` text, struck through.
- **`today-view`**: a three-tile KPI strip (to apply, to review, follow-ups due), then two tables.
  - "Relances du jour" (shown only when follow-ups are due): the due date, with the days late in
    stretch ink.
  - "À traiter": the job table with Status.
  - Headings are 13px, weight 600.
- **`track-form`**: the top of a `details-row`, above the meta line, closed by a 1px hairline.
  - Fields:
    - status select, then the two dates (150px each);
    - CV link (`https:` only) with an "Open" link once it is valid;
    - a full-width note textarea, which shows a counter in its last 200 characters.
  - Inputs follow `text-input`.
  - Errors appear under the field in danger ink, with `aria-invalid` and a danger border.
  - The foot holds four verdict pills (pressed = solid `{colors.primary}`) and a right-aligned
    save state:
    - "Saving…" in subtle ink;
    - "Saved" in success ink;
    - the error in danger ink, weight 500, followed by a Retry `button-secondary`.
  - Under 768px the fields go to two columns, the pills are 44px, and the save state takes its
    own line.
- **`quick-actions`**: two small pills in their own column before Lien, "À candidater" and
  "Ignorer". They sit on `{colors.surface-2}` with subtle ink and no outline at rest; hover
  brightens the text and adds a `{colors.hairline-strong}` border. They show only what makes
  sense (to review: both; to apply: Ignorer; ignored: À candidater) and never open the row. They
  are 44px tall under 768px, on their own line of the card.
- **`toast`**: fixed at the bottom centre, `{colors.surface-3}`, `{rounded.md}`, 13px, the one
  shadowed element (it floats). It holds the message plus a link button (Annuler / Réessayer). It
  disappears after 5 s and stays while hovered or focused (`role="status"`, polite).
- **`grouped-row`**: the same employer and normalized title in several departments is one row.
  The Dép. cell reads "3 dép." in link ink, with the list as its tooltip. The status shown is the
  most advanced posting's. The details list every posting (location, short date, its own status
  select, link) above the why-panel.
- **`triage-card`** (Tri, density 6 / motion 4): one card, at most 720px, centred.
  - Fill and border: `{colors.surface-1}`, 1px hairline, `{rounded.lg}`, 24px 28px padding.
  - Top row: badges ("Nouveau" primary-soft, "À tenter" stretch-soft) and the score as a 28px
    figure over "/100", in the section colour.
  - The title is 22px weight 600, then one facts line in subtle ink.
  - Then the top 3 reasons ("kubernetes · poids +3", success or stretch ink), the skill chips,
    and the description excerpt: 15px / 1.55, three lines, "Lire la suite".
  - "Voir l'offre" sits bottom right.
  - The next card peeks 12px below, scaled 0.96 at 55 % opacity. Only these two cards exist.
  - Dragging follows the pointer with at most 6° of tilt; a "Garder" or "Écarter" tag fades in
    with the distance. Past 30 % of the width, or flicked, the card flies out in 200 ms; under
    reduced motion it swaps instantly.
- **`swipe-controls`**: three buttons, 52px (56px on phones, sticky at the bottom).
  - Écarter: danger-soft. Annuler: neutral, disabled when there is nothing to undo. Garder:
    success-soft, solid success on hover.
  - Each shows its key (← Z →) in a quieter weight.
- **`reason-bar`**: after a left swipe, a `{colors.surface-2}` strip with "Pourquoi ?", four
  quick-action pills (Hors sujet, Trop senior, Compétence manquante, Lieu) and "Passer". It
  closes after 6 s.
- **`progress`**: a 6px primary bar with "Lot 1/8 · 7 / 20 · 134 restantes" in tabular figures.
  The batch-end and "Tri terminé" screens reuse the card surface, with a 22px heading and one
  primary button.
- **`pending-banner`**: danger-soft, "N actions en attente de connexion · Réessayer".
- **`kanban-column`**: four columns (two under 1100px, stacked under 768px):
  - `{colors.surface-1}`, `{rounded.lg}`, a 13px heading with its count;
  - the drop target tints primary-soft while a card is dragged over it.
  - "Relances dues" sits above the board in a stretch-soft band.
- **`kanban-card`**: `{colors.surface-2}`, `{rounded.md}`, 12px padding.
  - Title 14px weight 500, meta and dates 12px (dates in stretch ink when due).
  - Below them: the status menu, "J'ai postulé" (small primary) and the offer link.
  - The follow-up prompt "Relance le 28/10 ? Oui · Changer · Non" goes under the card.
  - Dragging lifts the card with the one floating shadow.
- **`filters-bar`** (phones): the "Filtres (n)" summary is sticky at the top of the panel and
  counts active filters.
- **Language**: the whole interface is in French (sentence case), units with a non-breaking space
  ("3 ans", "21 j"), dates via `fr-FR`.
- **`track-banner`**: `stretch-soft` field, 13px, `{rounded.lg}`. Shown when tracking cannot load
  (a page opened from a file, or the API refused), with Retry when a retry can help.
- **`why-panel`** ("Pourquoi cette offre ?"): a `<details>` closed by default, below the track
  form, the meta line and (for a group) the postings list. The summary is 13px weight 600,
  followed by the counts in subtle ink ("16 compétences · 4 non trouvées · 1 malus").
  - Two columns: "Compétences détectées" on the left; "Non trouvé dans ton profil", "Expérience"
    and "Ce qui a baissé le score" stacked on the right. "Ton avis" (the four verdict pills, with
    their own save state) spans both. One column under 768px.
  - Block headings are 12px weight 500 in `{colors.ink-subtle}`.
  - Each block shows **chips only**, wrapped inline: `tag-pos` matched, `tag-miss` unlisted,
    `tag-neg` lowering. A chip with a sentence is a button (`aria-expanded`); clicking it shows
    that sentence under the list, one at a time per block.
  - The weight reads "poids +3" in subtle ink with tabular figures; its tooltip and
    `aria-label` say what it does ("Ajoute 3 points au score de cette offre").
  - The experience sentence is behind a "voir la phrase" link button.
  - Missing preferred skills sit under the skills as `tag-miss` pills, labelled "sans effet sur le
    score": they never lower it.
  - "Toutes les explications (N)" folds the raw explanation list, translated for display.
- **`evidence-snippet`**: a `<q>` (French quotes from `lang="fr"`), 12px `{colors.ink-subtle}`,
  8px left padding behind a 2px `{colors.hairline-strong}` rule, wraps anywhere. Always text.
- **`confidence-badge`**: pill, 12px weight 500, after "N ans requis".
  - *chiffre explicite*: `success-soft` fill, success ink.
  - *mot-clé de séniorité*: `stretch-soft` fill, stretch ink.
  - *inconnu*, *non mentionné*, *non recalculé*: hairline border, `{colors.ink-subtle}`.
  - The "hors stage et alternance" flag is a `stretch-soft` pill under the sentence.
- **`override-button`**: "je maîtrise", a small `button-secondary` (28px, 44px under 768px),
  right-aligned on the unlisted skill's line.
  - Once saved, it becomes "Ajouté — compté au prochain run" in success ink plus an "Annuler" link
    button in link ink.
  - It saves optimistically. On failure it reverts, shows the error in danger ink and a Retry. Every
    control for the same skill on screen follows the change.
