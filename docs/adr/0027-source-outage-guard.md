# ADR 0027: Source outage guard — a dead API closes nothing

**Status:** accepted, 2026-11-06

## Context

On 2026-11-06 France Travail's API was down: every search answered 0 offers and every offer
page answered « n'existe pas ». The closure check (ADR 0010) reads 204 and 404 as CLOSED, so a
run taken at face value would have closed every stored France Travail offer, hidden them from
the digest and the dashboard, and turned every « À candidater » application « Expirée » (ADR
0024). The same failure mode exists for every ATS board (ADR 0020): a board answering 200
with an empty list is a complete listing where every stored id is "gone", and a Workday or
SmartRecruiters tenant whose search is broken closes its offers one probe at a time.

`ops check-sources` already emails when a source fetched 0 three runs in a row, but it runs
after the closures are written, and three days late.

## Decision

1. **Detection per source and per run** (`pipelines/outage.py`, thresholds in
   `settings.yaml` → `outage_guard`, read by a test). A source is down this run when:
   - it fetched 0 while the mean of its last `history_runs` (7) stored runs where it ran and
     was not down is ≥ `min_average_fetched` (20); or
   - more than `max_failed_ratio` (50 %) of its requests failed: 5xx after the client's
     retries, timeout, transport error, refused token. Every source now exposes
     `request_stats -> RequestStats(attempted, failed)` (France Travail, ats); a 404 or a 204
     is an answer, not a failure; or
   - the closure check says "gone" for more than `max_closed_ratio` (30 %) of at least
     `min_checked` (10) offers asked (`closure_outage`, after the answers are in).
   An **ATS board alone** is down when it lists 0 postings after ≥ `board_min_previous` (5)
   on the previous run (`by_board` stored with each run): only that board's offers are
   spared, the other boards and sources run as usual.
2. **Effects of an outage.** `check_closed` does not ask about the offers it covers (a
   `SourceOutage.covers(source, source_job_id)`), and when the closure ratio fires it writes
   nothing for that source, not even the open marks: every offer is asked again tomorrow.
   Nothing is closed, so no application turns « Expirée » because of that source (ADR 0024
   derives « Expirée » from `closed`). The other sources, the snapshot and the site are
   untouched. `ClosureStats.suspended` and `by_source[name]` (`checked`, `closed`,
   `suspended`) count what was withheld; `RunSummary.outages` carries the outages as
   `{source, label, kind, reason, boards}` and is stored in `runs.summary_json`.
3. **Visibility.** The GitHub job summary (`jobs_markdown`) adds Checked / Closed / Suspended
   per source and one line « ⚠️ <source> indisponible — clôtures suspendues : <raison> » per
   outage; the Exécutions page shows the same line on the run card (`.run-outage`) and the
   per-source counters; the digest says « <source> indisponible aujourd'hui » instead of
   « 0 unnotified jobs » when the day's run read a whole source as down (`today_outages`,
   subtitle, HTML banner, plain text, and `digest_markdown`). `ops check-sources` emails an
   alert through the same `send_text` as the silent-source alert, **once a day per source**:
   an outage already carried by an earlier jobs run of the same UTC day is not announced
   again (`outage_alerts`).
4. **Repair.** `job-match ops reopen --since YYYY-MM-DD --source NAME [--dry-run] [--apply]`
   (`ops/reopen.py`): for every jobs run since the date that was marked down for the source,
   or that closed more than the threshold of what it asked (per source when the run stored
   those counters, the run's totals for runs older than this ADR), every job of the source
   marked closed between the run's start and end is reopened (`closed_at` and
   `last_checked_at` cleared). Dry-run by default; `--apply` writes. Never run against the
   production DB from a dev machine without the dry-run first.

## Alternatives considered

- Reading 404 as UNKNOWN for France Travail: hides real closures forever (ADR 0010 observed
  no 404 on open offers) and does nothing for a board answering an empty 200.
- A global "too many closures" cap only: the 2026-11-06 run would still have asked 300
  offers for nothing, and a board with 3 stored offers would never reach the minimum; the
  per-board rule and the request ratio catch the outage before any closure call.
- Writing an `expired` or `suspended` state on the jobs: nothing to undo later; the guard
  simply writes nothing, and `reopen` covers the runs that preceded it.
- Making `check_closed` stop every source when one cannot be asked (the previous behaviour):
  one dead token must not spare the ATS boards their check; it now stops that source only.

## Consequences

- A healthy run changes nothing: the same closures are written, `suspended` is 0, no banner.
- A source enabled for the first time has no history, so 0 results alone is not an outage
  until it has run once; the request ratio still protects it.
- The guard's thresholds are settings: a source whose normal volume falls under 20 a day
  needs `min_average_fetched` lowered, or its 0 days are read as quiet days.
- Runs stored before this ADR carry no `outages`, `by_board` or per-source closure counters:
  the board rule needs one run with `by_board` before it can fire, and `reopen` falls back to
  the run's total closure ratio for them.
