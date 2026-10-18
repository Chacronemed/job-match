# ADR 0007 — A location must be positively French

**Status:** accepted (2026-10-18)

## Context

The digest filled up with US offers from Jooble: Washington DC, Bethpage NY, Arlington VA. Two
layers let them through, and both were measured before being changed.

- **The query.** ADR 0005 sent Jooble an empty `location` nationally, reading jooble.org as "the
  French index". It is not. `scripts/jooble_location_probe.py` (4 calls, page 1, the profile
  keywords, 2026-10-18):

  | host | location | totalCount | returned | French | abroad | unknown |
  |---|---|---|---|---|---|---|
  | jooble.org | `""` | 18 669 | 50 | 0 (0%) | 46 | 4 |
  | jooble.org | `"France"` | 16 | 16 | 16 (100%) | 0 | 0 |
  | fr.jooble.org | `""` | HTTP 403 | | | | |
  | fr.jooble.org | `"France"` | HTTP 403 | | | | |

  An empty location is the whole world. `"France"` is a literal filter: only the offers whose
  location string says "France", 16 of them, fewer than one region returns. There is no national
  query.

- **The gate.** `location_allowed` kept everything it could not prove was abroad, and the proof was a
  hand-made table: ~170 French cities and ~90 foreign markers in `fr_geo.py`. "Bethpage, NY" was in
  neither, so it was *unknown*, and unknown was kept. Growing the foreign list cannot win that race.

## Decision

1. **Jooble runs one query per French region.** `sources.regions` in `settings.yaml` now lists the
   13 metropolitan regions, the factory always passes them to the quota-light sources (no more
   `[""]` substitution), and `jooble.max_calls_per_run` is 26 so every region affords two pages.
   Alternatives: `"France"` (100% French, 16 offers: useless); a French host (403).

2. **Under `location_scope: france` a location must be positively French**, for every source except
   France Travail. Positive means a department prefix ("92 - Nanterre"), a commune, department,
   region or district name, a postal code, or the word "France" (`french_location(...) is True`).
   Jooble and Adzuna index the whole world, so a location we cannot read there is far more often
   Bethpage than a French hamlet nobody listed, and it is now rejected with `LOCATION`. France Travail
   is French by construction: its offers are kept unless filed under the abroad code 99 or naming a
   foreign place. A restricted scope (department list) keeps its old rule — unknown is kept, it was
   fetched for one of those departments — but now rejects a clearly foreign location too.
   Alternative: keep "unknown is kept" and filter at digest time. That hides the problem instead of
   fixing it, and the run summary would keep counting US offers as eligible.

3. **The hand-made city list is replaced by the official communes list.** `scripts/build_fr_communes.py`
   downloads the current communes and the municipal arrondissements from geo.api.gouv.fr (INSEE
   data), keeps only rows with a real department code and a plain name, and writes
   `src/job_match/normalization/fr_communes.tsv`: 35 013 rows, 32 721 distinct normalized names,
   540 KB, shipped as package data and loaded lazily. A name shared by several communes
   ("Saint-Denis": 93, 974 and two villages) keeps all of them, so `department_of` says "no single
   department" and the dedup block falls back to the text, as before for unlisted towns.
   Alternative: keep growing the hand list. It was already 170 entries and still missed
   "Châteauneuf-d'Ille-et-Vilaine".

4. **One scanner for every name.** `location._scan` tokenizes the normalized location and looks up
   n-grams longest-first in a single table (regions, department names, business districts, foreign
   markers, communes, first writer wins). A matched span is consumed, so "Porto-Vecchio" never
   trips the "porto" marker and "Haute-Savoie" is not Savoie. A name under three letters ("Y", "Eu")
   counts only as the whole location. One regex per name, the old design, cannot scale to 35k
   names; this is a few dict lookups per token (2 000 locations in 30 ms).

5. **US-style "City, ST"** is detected on the raw string: a two-letter US state or Canadian province
   code after a comma at the end ("Bethpage, NY", "Austin, TX, USA"), anchored so "Paris, LA DEFENSE"
   is not Louisiana. It runs before the commune lookup, so "Saint-Louis, MO" is Missouri. The foreign
   marker list gains the US state names, "usa", "uk" and the big North-American cities.

6. **Ligatures are spelled out in `normalize_text`** ("Courtabœuf" → "courtaboeuf"): NFKD leaves
   them alone, so the communes file would otherwise have dropped 110 rows and never matched the
   "oe" spelling job boards use. This changes the fingerprint of a posting whose text contains a
   ligature; `job-match reprocess` recomputes fingerprints, so the next cleanup absorbs it.

## Consequences

- A Jooble or Adzuna job with an empty or unreadable location is rejected on `LOCATION`. That is
  the trade: a French job in a place the official list does not know (a lieu-dit, a business park
  not in `EXTRA_PLACES`) is lost, and the fix is one line in `EXTRA_PLACES`, never a gate change.
- `departments_for` is empty for a foreign location as well as an unknown one; callers that need
  the difference ask `french_location`.
- `job-match reprocess` now prints the per-department block, so the "?" bucket (no single
  department) is visible on stored data. On the local DB (533 France Travail rows, all prefixed) the
  reprocess changed nothing: 0 `LOCATION`, no "?" bucket. The US rows live in the production DB and
  are cleaned by the Daily run's `reprocess_since` input.
- Jooble's depth per region drops from 10 pages (one worldwide query) to 2. Raise
  `jooble.max_calls_per_run` rather than trimming regions if depth matters.
- `fr_communes.tsv` is rebuilt by hand when communes merge (yearly); nothing checks its age.
