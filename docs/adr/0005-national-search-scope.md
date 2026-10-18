# ADR 0005 — National search scope (`location_scope`)

**Status:** accepted (M14, 2026-10-16)

## Context

Geography was a 14-entry `ft_search.departments` list plus a 10-entry `filters.locations` city
list. Two lists, two meanings, and both wrong for a candidate who is mobile across all of France:
France Travail was queried per department, so an offer in Toulouse was never fetched, and the gate
rejected anything whose department was not in the list even when the offer did arrive (from Jooble,
which queries regions).

One external constraint shapes the France Travail side. The search endpoint exposes a **window**,
not a cursor: the `Range` start may not exceed 1000 and its end may not exceed 1149. With 150-offer
pages a single query therefore reaches **1050 offers over 7 pages** and no more. Per department
that ceiling was unreachable; a nationwide `motsCles=devops` hits it.

## Decision

1. **One profile key: `location_scope`.** `france` (also `fr`, `national`, `all`, empty) searches
   and accepts the whole country; a list (`["75", "92"]`) restricts both. It is parsed in
   `config/loader.py` into `FTSearch.departments`, where **empty already meant "no department
   filter"** to the France Travail adapter — so the new setting has exactly one in-code
   representation, read by every source and by the gate. `FTSearch.national` names the condition.
   The legacy `ft_search.departments` list is still accepted when `location_scope` is absent, so an
   old profile — or an un-updated `PROFILE_YAML` secret — keeps working.

2. **`filters.locations` is gone from the profile.** A second geography list is exactly what this
   ADR removes. The field survives in the schema as an optional city allowlist for a restricted
   scope; the shipped profile does not use it.

3. **France Travail: one paginated query per keyword, no `departement` param**, with the window
   enforced in the adapter: `MAX_RANGE_START = 1000`, `MAX_RANGE_END = 1149`, the last range
   clamped, and paging stopped when no further page is addressable. Truncation is **logged as a
   WARNING** naming what was reachable against what the API says exists — a national search that
   silently drops 80% of a keyword's offers would be worse than no national search.

4. **An HTTP 400 on a paged request ends that query, not the run.** A refused range is a
   France-Travail-side boundary, not a reason to lose the other keywords. One WARNING, then the
   next keyword.

5. ~~**Jooble sends no location at all** when the scope is national~~ **Superseded by
   ADR 0007 (2026-10-18):** the empty location is the whole world (0% French on a 50-offer
   page), so Jooble now runs one query per French region. The original text follows.
   **Jooble sends no location at all** when the scope is national
   (`adapters/jobs/factory.py` substitutes `[""]` for the region list), and spends its whole call
   budget on depth instead of breadth: `pages_per_region = max_calls_per_run // len(regions)` is
   the full budget when there is one query. Measured, not assumed: Jooble's `location` is a
   literal place filter, and on 2026-10-16 `"France"` matched **16** offers for our keywords while
   an empty location matched **18168**. `sources.regions` in `settings.yaml` stays for a restricted
   scope.

6. **The gate asks a different question nationally.** There is no department list to match, so
   `normalization/location.french_location()` returns a tri-state — `True` clearly in France,
   `False` clearly abroad, `None` cannot tell — and the gate rejects only `False`. `None` keeps the
   job, as unknown experience, unknown contract and unreadable locations already do. Two tables
   back it (`normalization/fr_geo.py`): `FRENCH_DEPARTMENTS`, because France Travail files offers
   abroad under the fake department `99`, and a short `FOREIGN_PLACES` marker list. Foreign markers
   are checked **before** city names, so "Lille, Belgique" is Belgium, not Nord.

7. **`by_department`, parsed from each offer's own location, replaces `by_area` as the geographic
   signal** (`RunSummary.by_department`, filled in `pipelines/jobs.py` via
   `location.department_of`, top 10 printed by `cli._print_summary`). With one national query
   `by_area` degenerates to `all`, so "where are the offers" has to come from the offers. It counts
   rejected offers too: it answers where the market is, not where the matches are.

## Alternatives considered

- **Keep a fan-out, one query per keyword × region (13 regions).** It would beat the window — each
  region's result set stays under 1050 — at ~91 calls per run. Rejected for now because the request
  was an explicit nationwide query, and because truncation is visible in the logs: if the warning
  shows up every day, this is the fix to reach for.
- **Pass `since` so each daily query only asks for new offers.** Also dodges the window, and is the
  natural next step once the pipeline runs daily, but it makes the first run of a fresh database
  shallow. Kept as an option, not a dependency of this change.
- **A full commune → department dataset** (La Poste / INSEE CSV) instead of the hand-written
  `fr_geo` tables. More accurate, but a data dependency to vendor and refresh for a gate whose
  unknown case already keeps the job. `fr_geo` grows when a real location is missed.
- **An allowlist of French place names instead of a foreign marker list.** It would have to be
  exhaustive to avoid rejecting real French towns, which is the data dependency above with a worse
  failure mode: a missing town would be *rejected* instead of kept.
- **Keep both `location_scope` and `departments` as live keys.** Two sources of truth with a
  precedence rule to remember. The deprecated-alias path exists only so an old file still loads.

## Consequences

- The reachable market grows from 14 departments to the country: Toulouse, Nantes, Rennes,
  Strasbourg, Lille, Marseille and the DOM now arrive and are scored. Expect more offers, more
  noise, and `LOCATION` rejections only for foreign postings.
- A keyword with more than 1050 live offers nationwide is truncated by the API, with a WARNING per
  query. The run is still complete in the sense that matters — it just saw the first 1050.
- CI keeps searching the old 14 departments until the `PROFILE_YAML` secret is re-encoded from the
  updated `config/profile.yaml`. The deprecated alias is what makes that merely stale, not broken.
- `FOREIGN_PLACES` is a short list: a foreign city nobody listed resolves to `None` and its job is
  kept. The failure mode is noise in the digest, never a silently dropped French job.
- Relocation-only offers ("poste basé à Genève") are now rejected, which is the point, but a French
  employer whose location field names a foreign HQ is collateral damage. The reason is recorded on
  the job, so it is auditable.
