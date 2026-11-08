# Product

<!-- impeccable:product-schema 1 -->

> Written by `/impeccable init` on 2026-11-07 (branch `design/impeccable-pass`). The interview
> answers come from the owner's brief for this pass (single user, three key tasks, desktop and
> mobile, AA); everything else is taken from `README.md`, `CLAUDE.md`, `docs/PROJECT_BRIEF.md`
> and `docs/design/`. Visual decisions live in `docs/design/DESIGN.md`, not here.

## Platform

web

## Users

One person: the owner, a junior DevOps engineer (about two years of experience) looking for a
CDI in France. There is no other audience, no team, no admin, no sign-up. The dashboard is
private (Cloudflare Access) and opened on a desktop at home and on a phone between two things,
usually after the morning run has collected the day's offers.

## Product Purpose

job-match collects French job offers every morning, rejects the ones that do not fit (off-topic,
too senior, wrong contract, outside France) before any scoring, scores the rest with an
explainable rule engine, links them to funding news, and emails one digest. The dashboard is
where the owner acts on that work. Success is a short, confident daily session: the new offers
are triaged, the applications that need a follow-up are followed up, and nothing is lost or
sent twice.

The three key tasks, in order of frequency:

1. **Trier vite** — go through the new offers one at a time and keep or drop each, with a
   reason for a drop (`#tri`).
2. **Comprendre un score** — read why an offer scored what it scored: matched and missing
   skills, maluses, the experience gate, the AI's opinion when there is one (`#offres`, the
   record panel, the Tri card's « Relevé du score »).
3. **Postuler et suivre** — generate the CV and cover letter, mark « Candidature envoyée »,
   follow up on time, confirm recruiter replies (`#candidatures`).

Statistiques, Leads (funding signals) and Exécutions (what the pipeline did) support these
tasks; they are consulted, not worked in.

## Positioning

A job search tool built for exactly one candidate profile, whose every number is traceable: the
score is a ledger of named skill weights read from `config/profile.yaml`, the experience
requirement is a hard gate that runs before scoring (an unknown requirement says it is unknown),
and a funding lead is never presented as a job. A generic job board cannot show « pourquoi
cette offre te correspond » line by line.

## Operating Context

- Daily rhythm: the GitHub Actions run collects and scores in the morning, rebuilds the static
  dashboard and emails the digest; the owner then triages on the dashboard.
- The dashboard is a static page (`src/job_match/dashboard/`) plus a Cloudflare Worker that
  stores the owner's tracking (statuses, decisions, notes), AI verdicts, generated documents
  and recruiter replies. Without the Worker the page still shows the snapshot read-only.
- career-ops is a companion tool used by hand on shortlisted offers; it is never a dependency.
- Sources can be down (France Travail outage of 2026-11-06, ADR 0027); the page must say so
  rather than present an empty day as a quiet one.

## Capabilities and Constraints

- Stack: static HTML / CSS / vanilla JS, rendered by Python (`render.py`), Cloudflare Worker for
  the API. No framework, no CDN, no build step for the page; strict CSP (`script-src 'self'`
  plus hashes, no `unsafe-inline` JS, fonts self-hosted).
- Views: Tri, Offres, Candidatures, Statistiques, Leads, Exécutions; hash routing, command
  palette, keyboard shortcuts for every action.
- French UI copy, « tu », sentence case.
- Never invented data: every number on screen comes from the snapshot or the Worker; unknown is
  shown as unknown. CVs and letters are generated only from `private/cv_master.yaml`.
- Undecided: a « Aujourd'hui » home view (evaluated in `docs/design/IMPECCABLE_AUDIT.md`, not
  built).

## Brand Commitments

- Name: job-match. No logo beyond the violet square mark; no marketing surface.
- Voice: direct French, second person, says what happens and what to do next.
- Binding visual system: `docs/design/DESIGN.md` (Focus, ADR 0025) and
  `docs/design/JOB_MATCH_FOCUS.md`.

## Evidence on Hand

- Real data lives in a private repository and in D1; it is never used for previews or
  screenshots. Design work uses the test seed (`tests/unit/conftest.py`) and mocked API
  payloads (`tests/unit/browser/`).
- No testimonials, users, metrics or claims exist to show, and none may be invented.

## Product Principles

1. **Decide in seconds, verify in one click.** The fast path (Tri) never hides the evidence
   path (the record).
2. **Every number is explainable or absent.** No score, count or claim without its source.
3. **Unknown is a value.** Missing experience, company, AI opinion or tracking is said, never
   filled in.
4. **The machine reports, the owner decides.** The pipeline and the AI propose; only the owner
   keeps, drops, applies.
5. **Same task, any screen.** Every key task works at 390 px with touch and at 1440 px with the
   keyboard.

## Accessibility & Inclusion

WCAG 2.2 AA in both themes (dark and light): text contrast 4.5:1 (3:1 for large text), visible
focus, every control reachable by keyboard, 44 × 44 px touch targets below 768 px, status never
carried by colour alone, `prefers-reduced-motion` honoured.
