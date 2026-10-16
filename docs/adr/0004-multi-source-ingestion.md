# ADR 0004 — Multi-source job ingestion (Jooble, Adzuna)

**Status:** accepted (M13, 2026-10-16)

## Context

France Travail alone misses the market we care about: startups and scale-ups that have just
raised post their roles on aggregators and on their own site, not on the public service. Adding
boards is the cheapest way to widen coverage without touching the scoring or the digest.

The two candidates behave nothing like France Travail:

- **France Travail** — generous quota, 150 results per page, filters by department code. We
  already fan out one query per keyword × department (98 calls per run, 14 departments).
- **Jooble** — free plan of a few hundred calls a day. One keyword and one location per request.
- **Adzuna** — free tier is too small to be useful; the usable plan is paid. `what_or` accepts
  OR'd keywords, so all keywords fit in one request per location.

Running the France Travail fan-out against either would burn a daily quota in one run. Their
locations are also plain names ("Nanterre", "Île-de-France"), which the location gate — built on
France Travail's `"NN - City"` prefix — rejected outright.

## Decision

1. **Two adapters behind the existing `JobSource` protocol**
   (`adapters/jobs/jooble.py`, `adapters/jobs/adzuna.py`). No change to the domain model: every
   source-specific field name stays inside its adapter, as in `france_travail.py`.

2. **Keyword × region, never keyword × department, for the quota-light sources.** Regions live
   in `settings.yaml` (`sources.regions`); keywords stay in the private profile
   (`ft_search.keywords`) because they are personal and regions are not. Page 1 only — with a
   few hundred calls a day, breadth beats depth. Adzuna spends one call per region instead of
   one per keyword × region, because `what_or` is OR semantics.

3. **A hard per-source call budget**, `sources.<name>.max_calls_per_run` (Jooble 15, Adzuna 20),
   checked before every request. Hitting it logs a WARNING and ends that source's run; calls
   used are logged and reported per source in the run summary. The cap is in config, not code,
   so a plan change is a one-line edit.

4. **Credentials from the environment only** (`JOOBLE_API_KEY`, `ADZUNA_APP_ID`,
   `ADZUNA_APP_KEY`), declared per source in `adapters/jobs/factory.py`. A source that is
   enabled but has no key is skipped with one WARNING and the run continues: a missing Jooble
   key must never cost us the France Travail run. Only an empty source list is fatal.
   `sources.enabled` decides what runs, and Adzuna is left out of it until the plan is paid.

5. **`departments_for(location)` resolves all three location formats**
   (`normalization/location.py` + the `fr_geo.py` tables): the `"NN - City"` prefix, a known
   city or department name, or a region name (every department in it). The gate passes when the
   result overlaps the departments we query, and **keeps the job when the result is empty** —
   the same rule as before, applied to more formats. Region data is reference data, not
   configuration, so it lives in the package rather than in `config/`.

6. **Contract `UNKNOWN` no longer rejects.** Jooble ships free text ("Full-time") and Adzuna a
   label that means nothing precise in France ("contract"), so demanding a parsed contract type
   would reject nearly every non-France-Travail job. This matches how the gate already treats
   unknown experience and unreadable locations: we never reject on something we could not read.
   A *stated* contract outside the filter is still a rejection.

7. **Cross-source dedup blocks on the company alone**, not on
   `(company, contract_type)`. The same offer on Jooble usually carries `UNKNOWN` contract, so a
   contract-keyed block would never compare the two rows. Sources are drained in
   `sources.enabled` order inside one dedup pass: the first source to report an offer gets the
   canonical row, the next gets a `job_duplicates` link. Nothing is deleted.

8. **Secrets must not reach the logs.** Jooble puts the API key in the URL *path* and Adzuna
   puts credentials in the query string, and httpx logs the full URL at INFO — straight into a
   public Actions log. `cli.py` therefore keeps the `httpx`/`httpcore` loggers above INFO, and
   each adapter logs its own aggregate line per query with the URL redacted (`<key>`).

## Alternatives considered

- **Scrape the boards instead of using their APIs** — more coverage, but fragile, slow, and a
  terms-of-service problem. Rejected.
- **One shared "aggregator" adapter parameterised per board** — the two APIs differ in method
  (POST vs GET), auth placement, pagination and field names. Two small explicit adapters are
  shorter to read than one branching one.
- **Keep the keyword × department fan-out and throttle harder** — 98 calls would exhaust a daily
  Jooble quota in a single run, with most calls returning the same offers.
- **Treat an unknown contract type as a rejection and parse harder** — guessing CDI from
  "Full-time" invents a fact the posting does not state (CLAUDE.md rule 3's spirit).
- **A separate `locations`-style config list per source** — a second geography list to keep in
  sync with `ft_search.departments`. Rejected for the same reason the gate reads the department
  list it already queries.

## Consequences

- Coverage grows without touching normalization, scoring, dedup logic or the digest.
- The duplicate rate will rise: the same offer now arrives from two or three places. That is
  visible as `duplicates` per source in the run summary, not as lost rows.
- `UNKNOWN` contract jobs now reach scoring. If that proves noisy, the fix is a scoring penalty,
  not a gate rejection.
- `fr_geo.py` is deliberately incomplete and will need entries as the region list grows. An
  unlisted city is kept, so the failure mode is noise, never a silently dropped job.
- Adding a fourth board means: one adapter, one `REQUIRED_ENV` entry, one branch in
  `build_sources`, and its name in `sources.enabled`.
