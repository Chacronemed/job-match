# ADR 0002 — Article ingestion stores a short extract, never the body

**Status:** accepted (M10, 2026-10-04)

## Context

The funding pipeline discovers articles through RSS (Maddyness, FrenchWeb) and will later
(M11) extract structured funding facts from them. The brief forbids storing full articles
(§13) and the repo is public, so anything persisted must be small and non-sensitive.

Both feeds were probed live on 2026-10-04: Maddyness returns 10 entries per fetch (its feed
is served as `text/html` but parses fine), FrenchWeb returns 100. Trafilatura extracts the
main text of both sites without custom HTML rules.

## Decision

1. **Store only a short extract** (`articles.extract`, default 600 chars, word-boundary cut)
   plus `source, url, title, published_at, collected_at`. The full text lives in a local
   variable inside `pipelines/funding.py` and is discarded after the extract is taken. M11
   will plug the structured extraction into that same spot, so the body never needs to be
   persisted.
2. **Dedup key is the normalized URL** (`normalize_article_url`: tracking params stripped,
   lowercase scheme/host, no fragment, no trailing slash). Seen URLs are skipped *before*
   any article fetch. First seen wins across sources.
3. **Fetch every new article, no keyword pre-filter yet.** Feeds are small and dedup means
   only new entries are fetched after the first run (~10–20/day at 1 req/s). The
   funding/non-funding decision belongs to M11, which owns the `is_funding` column.
4. **A failed fetch or empty extraction is counted as an error and not stored**, so it is
   retried on the next run while the entry is still in the feed, then naturally dropped.
5. **Feed URLs are adapter constants**, not config, like the France Travail endpoints.
   `settings.yaml` only selects which sources run and the politeness/extract parameters.

## Alternatives considered

- Store the full text for M11 to consume later: violates brief §13, bloats the public-adjacent
  data repo, and is unnecessary since extraction can run in the same pass.
- Keyword pre-filter before fetching (as sketched in ARCHITECTURE §6): saves a few requests per
  day but couples ingestion to funding vocabulary; deferred to M11 where it can be measured.
- Store failed articles with a null extract to avoid retries: simpler bookkeeping, but hides
  transient failures and leaves M11 with unusable rows.

## Consequences

- Migration `0003_add_article_extract.sql` adds the nullable `extract` column.
- `RunSummary` gains `feeds`; the funding summary maps found → `fetched`, new → `articles`,
  skipped → `duplicates`.
- `HttpClient` now sends a fixed `User-Agent` and can follow redirects (both feeds redirect).
