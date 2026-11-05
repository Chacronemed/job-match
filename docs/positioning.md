# Positioning: job-match next to career-ops and CareerHound

*Written 2026-11-04. Facts about the two other tools were read from their public pages that
day (career-ops README, `providers/` and `modes/pipeline.md`; careerhound.io's landing page).
Anything they do not state publicly is marked as such.*

## One sentence each

- **job-match** (this repo): a deterministic, LLM-free, France-specific daily pipeline. It
  fetches offers from France Travail and from the public job boards of configured companies
  (Greenhouse, Lever, Ashby), rejects them against auditable eligibility rules, scores the rest
  with a rule engine whose every point is explainable, links them to funding news, and emails
  one digest a day. Single user, SQLite, GitHub Actions, no server.
- **career-ops** ([github.com/career-ops-hq/career-ops](https://github.com/career-ops-hq/career-ops),
  MIT, 80.2k stars on 2026-11-04): an open-source job-search agent that runs *inside* an AI CLI
  (Claude Code, Codex, OpenCode and others). Paste a job URL: it checks the posting is live,
  scores it 1-5 against your CV with an LLM, drafts a tailored CV, cover letter and answers, and
  adds a tracker row. A `scan` mode reads 55+ provider modules (ATS APIs, board feeds, RSS,
  local parsers) into an inbox, `data/pipeline.md`.
- **CareerHound** ([careerhound.io](https://careerhound.io)): a paid-preview web service that
  finds "jobs not on LinkedIn/Indeed" by indexing company career pages directly and linking to
  the original listing. Its FAQ says "mainly job postings written in English" and "jobs from
  every company we can find". Pricing and crawl method are not stated on the page; a user
  testimonial describes it as "scraping career pages".

## What each does better

| | job-match | career-ops | CareerHound |
|---|---|---|---|
| **Coverage of the French market** | Best. France Travail is the national board, with an INSEE communes list for the location gate and French experience wording ("3 ans minimum", "première expérience") parsed natively. | Weak by default: providers are global ATS APIs and English-language boards; no French board. | Weak: English postings first, company pages worldwide. |
| **Coverage of direct company postings** | Only the companies you list in `config/ats_boards.yaml` (30 verified French tech boards shipped). | Better: 55+ providers, per-company portal config, scanner with history and dedup. | Best in breadth: it crawls career pages of any company, including those on no ATS API. |
| **Scoring quality on one posting** | Rule engine: skill weights, title families, experience gate. Calibrated, explainable, but blind to nuance (a "DevOps" title at a bank vs a cloud provider reads the same). | Best: an LLM reads the whole posting against your full CV and explains fit per dimension (A-G grid). Costs tokens and time per posting. | None stated; it is a discovery tool, not a scorer. |
| **Eligibility rules** | Hard gates before scoring, each with a stored rejection reason: experience years, French location, relevance, contract. The same posting gives the same verdict every day; a wrong verdict is a test case. | The LLM decides; reasoning is readable but not reproducible, and a pre-screen gate can discard with a logged reason. | None visible. |
| **CV tailoring, cover letter, application answers** | Yes since M26 (ADR 0017), from a private master only, with a validator that refuses invented facts. Narrower than career-ops: no interview prep, no answers to application questions. | Best: full pipeline, PDF/LaTeX/text output, tracker, interview and negotiation modes. | No. |
| **Funding signals** | Yes: RSS from Maddyness and FrenchWeb, rule-based extraction with the evidence sentence per field, leads linked to the same companies' offers. Nobody else does this. | No. | No. |
| **Automation** | Fully unattended: one GitHub Actions job a day, email digest, dashboard behind Cloudflare Access. Zero tokens, zero cost beyond free tiers. | Interactive by design ("you press Submit"); batch and headless modes exist but each posting costs an LLM call. | Hosted; the user browses the site. |
| **Dedup across sources** | Fingerprint plus fuzzy matching, links stored with a reason, nothing deleted. | URL-keyed dedup in the scanner and tracker. | Unknown. |
| **Privacy** | Code public, data in a private repo; the model never sees contact details. | Local files; CV goes to the LLM provider you chose. | Your searches and profile live on their service. |
| **Cost to run** | Free (GitHub Actions, Cloudflare free tier, France Travail API). | Free software; tokens per evaluation. | Paid service (amount not published). |

## Where job-match stands

job-match is the **sourcing and triage layer** for one French DevOps job search. Its edge is
not intelligence but **determinism and audit**: a posting is accepted or rejected by rules you
can read, the score is a sum of weights you can change in `config/`, and every number in the
digest comes with the sentence it was derived from. That is what makes a daily, unattended run
trustworthy: the same input gives the same output, a false positive becomes a regression test,
and a run costs nothing.

What it deliberately does not try to be:

- A general job-search agent. career-ops already does the LLM-powered per-posting evaluation
  and the application paperwork, and does it well. Duplicating that would be the "god main.py"
  CLAUDE.md forbids.
- A crawler. CareerHound's breadth comes from crawling arbitrary career pages. job-match reads
  only documented public JSON endpoints (France Travail's API, Greenhouse/Lever/Ashby boards),
  respects `robots.txt` and never scrapes HTML behind a login.

## The hand-off to career-ops

The two tools meet on a file. Every day job-match can write its strongest matches in
career-ops' own inbox format:

```bash
job-match export --top 3 --format career-ops                 # data/export/career-ops-<date>.md
job-match export --top 3 --append ../career-ops/data/pipeline.md   # straight into its inbox
```

Each line is `- [ ] {url} | {company} | {title} | {location} | note: job-match {score}/100 |
posted: {date}`, the shape career-ops' `modes/pipeline.md` documents. The user then runs
`/career-ops pipeline` (or names the exported file as a lane) and career-ops does what it is
good at: read the full posting, grade it against the CV, and draft the application. Our score
travels as a `note:` so it is never mistaken for career-ops' own 1-5 grade.

Division of labour, in one line each:

- **job-match** decides *which* postings deserve an evening: fetch, gate, dedup, score, flag
  companies that just raised money.
- **career-ops** decides *how* to apply to them: evaluation against the CV, tailored documents,
  tracker.

## What job-match borrowed from career-ops

The ATS adapter (`src/job_match/adapters/jobs/ats.py`, ADR 0020) uses the same three public
endpoints as career-ops' `providers/greenhouse.mjs`, `lever.mjs` and `ashby.mjs`, and follows
their field mapping (posting URL, posting date, Lever's `lists` folded into the description,
Ashby's `isRemote` fallback). The code is a Python re-implementation, not a copy; the provider
modules are credited in the adapter's docstring under career-ops' MIT license.
