# ADR 0020: Company boards through public ATS JSON endpoints

**Status:** accepted, 2026-11-04

## Context

France Travail covers the national market but lags company sites by days and carries agency
reposts. Many French tech companies publish their postings on a hosted ATS whose board is also
served as an unauthenticated JSON document meant for embedding: Greenhouse
(`boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true`), Lever
(`api.lever.co/v0/postings/<slug>`) and Ashby (`api.ashbyhq.com/posting-api/job-board/<slug>`).
career-ops (MIT) reads the same three endpoints in its provider modules; their field mapping was
studied and re-implemented here (`docs/positioning.md`).

`config/companies.yaml` (M28) already lists 115 target companies with an unverified ATS guess;
nothing reads it.

## Decision

One new source, `ats`, implementing the existing `JobSource` protocol (`fetch`, `to_job`,
optional `query_stats`, `api_calls_count`, `check_offer`), driven by `config/ats_boards.yaml`:
a flat list of `{company, ats, slug}`. Thirty boards ship, each verified to answer 200 with
postings on 2026-11-04 by `scripts/ats_probe.py`; the unverified guesses in `companies.yaml`
stay where they are and are not read.

- One GET per board per run, one request per second (Lever's `robots.txt` asks for
  `Crawl-delay: 1`), the project's User-Agent, JSON only. No HTML page is fetched.
- A board that answers 404 or fails is logged and skipped; the others run. A run with every
  board down yields nothing and the pipeline continues on France Travail.
- `source_job_id` is `<ats>:<slug>:<id>`, so `check_offer` can answer from the board read in
  the same run: an id missing from a board that answered 200 is CLOSED, a board that could not
  be read is UNKNOWN (ADR 0010 semantics).
- The company name comes from the config, not from the payload (Lever and Ashby send none).
- Downstream nothing changes: the same experience gate, location gate (which keeps the French
  offices of a company and rejects its Warsaw or Madrid ones), dedup and scoring apply.

## Alternatives considered

- Reading `companies.yaml` directly: 115 unverified guesses, most on Workday, SmartRecruiters
  or custom sites that have no public JSON board. Verifying first and keeping a small clean list
  is simpler and honest about what works.
- One source per ATS (`greenhouse`, `lever`, `ashby`): three classes for one behaviour. The
  ATS name is kept as the `area` of each `QueryStat`, so the run summary still breaks fetched
  counts down per ATS.
- An HTML crawler for the companies with no JSON board: out of scope by rule (no scraping
  behind login, respect ToS) and by design (CareerHound's niche, not ours).

## Consequences

- `sources.enabled` gains `ats`; no credential needed, so it runs in CI as is.
- Adding a company is one YAML line after `scripts/ats_probe.py <slug>` shows it answers.
- Offers from foreign offices are fetched and rejected by the location gate; they count in
  `fetched` and in `rejected: LOCATION`, which is visible in the run summary.

## Amendment 2026-11-05 (M28): verify `companies.yaml` before reading it

- `job-match companies detect` checks each of the 115 companies against the public endpoints
  (the three above plus SmartRecruiters `api.smartrecruiters.com/v1/companies/<id>/postings`
  and Workday `POST <tenant>.<wdN>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs`): the ATS
  named in `careers_url`, else the links of one GET of the careers page (redirects followed,
  links only, nothing stored), else the name as a slug. **Verified = 200 with at least one
  posting**: an unknown SmartRecruiters id answers 200 with zero, so an empty board proves
  nothing. A board id without the company name (a parent group's board) is flagged.
  1 request/s per host. Results in `config/companies_detected.yaml`, read by no source yet:
  the Workday and SmartRecruiters adapters wait for the report's review.
- The tracking key of an `ats` offer is `ats:<ats>:<slug>:<id>` (up to ~70 characters with a
  Lever UUID): the key rule (`JOB_KEY_RE`, Worker `validate.js` / `ai.js`, `triage.js`)
  accepted neither the second `:` nor that length, so since this ADR the Worker refused every
  status write and AI verdict on an `ats` offer (400). The id part now allows `:` and 128
  characters.
- Offres gets a Source filter (source, or one company board) and a Source column; Exécutions
  lists fetched / eligible per company for `ats` (`by_company` in the run summary).
