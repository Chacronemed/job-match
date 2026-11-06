"""Source outage guard (ADR 0027): is a source down today, so that none of its offers may be
closed on its word?

On 2026-11-06 France Travail's API answered 0 offers to every search and "does not exist"
to every offer page. Taken at face value, that run would have closed every stored France
Travail offer and turned my « À candidater » applications « Expirée ». The guard reads a
source as down for the run when:

* it fetched nothing while it used to fetch plenty: 0 offers, and the mean of its last
  `history_runs` stored runs where it was not down is at least `min_average_fetched`;
* most of its requests failed: more than `max_failed_ratio` of the requests it made this
  run got no usable answer (5xx after the retries, timeout, network error, refused token);
* the closure check says "gone" far too often: more than `max_closed_ratio` of at least
  `min_checked` offers asked (`closure_outage`, computed by `pipelines/closure.py` once the
  answers are in);
* for the `ats` source, one board lists 0 postings after at least `board_min_previous` on
  the previous run: that board alone is down (`boards` names it), the others still run.

A down source changes nothing in the DB that day: its closures are not asked or not
applied, the other sources run as usual, the run summary carries the outage so the digest,
the GitHub summary, the Exécutions page and `ops check-sources` can say so. Everything here
is pure: it reads counters and stored run summaries and returns `SourceOutage`s.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from job_match.adapters.jobs.base import RequestStats
from job_match.config.schema import OutageGuardConfig
from job_match.domain.models import RunRecord

SOURCE_LABELS: dict[str, str] = {
    "france_travail": "France Travail",
    "ats": "Pages carrière (ATS)",
    "jooble": "Jooble",
    "adzuna": "Adzuna",
}

# `kind` values, also what the page and the tests key on.
NO_RESULTS = "no_results"
REQUESTS_FAILED = "requests_failed"
CLOSURES = "closures"
BOARD_EMPTY = "board_empty"


def source_label(name: str) -> str:
    return SOURCE_LABELS.get(name, name)


@dataclass(frozen=True, slots=True)
class SourceOutage:
    """One source (or a few boards of it) read as down for this run, and why."""

    source: str
    kind: str
    reason: str  # one French sentence, shown as is on the page and in the summary
    boards: tuple[str, ...] = ()  # BOARD_EMPTY only: "<ats>:<board id>" of the boards down

    @property
    def label(self) -> str:
        return source_label(self.source)

    @property
    def whole_source(self) -> bool:
        """Every offer of the source is spared; False when only `boards` are."""
        return not self.boards

    def covers(self, source: str, source_job_id: str) -> bool:
        """Is this offer's closure suspended by this outage?"""
        if source != self.source:
            return False
        if self.whole_source:
            return True
        return any(source_job_id.startswith(board + ":") for board in self.boards)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "label": self.label,
            "kind": self.kind,
            "reason": self.reason,
            "boards": list(self.boards),
        }

    @classmethod
    def from_dict(cls, d: Mapping) -> SourceOutage:
        return cls(
            source=str(d.get("source", "")),
            kind=str(d.get("kind", "")),
            reason=str(d.get("reason", "")),
            boards=tuple(str(b) for b in d.get("boards") or ()),
        )


def outages_of(summary: Mapping) -> list[SourceOutage]:
    """The outages a stored run summary carries (none for runs older than ADR 0027)."""
    return [
        SourceOutage.from_dict(d) for d in summary.get("outages") or [] if isinstance(d, Mapping)
    ]


def _down_in(summary: Mapping, source: str) -> bool:
    return any(o.source == source and o.whole_source for o in outages_of(summary))


def fetched_history(history: Iterable[RunRecord], source: str, runs: int) -> list[int]:
    """`fetched` of the source in its last `runs` stored jobs runs where it ran and was not
    down: what "normal" looks like. A run the source did not take part in (not enabled, no
    key) is skipped, not counted as 0."""
    values: list[int] = []
    for record in history:
        if record.pipeline != "jobs":
            continue
        counts = (record.summary.get("by_source") or {}).get(source)
        if counts is None or _down_in(record.summary, source):
            continue
        values.append(int(counts.get("fetched", 0) or 0))
        if len(values) >= runs:
            break
    return values


def _pct(ratio: float) -> str:
    return f"{round(ratio * 100)} %"


def detect_collection_outages(
    by_source: Mapping[str, Mapping[str, int]],
    request_stats: Mapping[str, RequestStats | None],
    by_board: Mapping[str, Mapping[str, int]],
    history: list[RunRecord],
    guard: OutageGuardConfig,
) -> list[SourceOutage]:
    """The outages the collection itself reveals, before any closure check: one per source
    at most (the first rule that fires), or one `BOARD_EMPTY` naming the boards down."""
    found: list[SourceOutage] = []
    previous = history[0].summary if history else {}
    for source in sorted(by_source):
        fetched = int(by_source[source].get("fetched", 0) or 0)
        prior = fetched_history(history, source, guard.history_runs)
        mean = sum(prior) / len(prior) if prior else 0.0
        if fetched == 0 and prior and mean >= guard.min_average_fetched:
            found.append(SourceOutage(
                source, NO_RESULTS,
                f"0 offre récupérée, contre {mean:.0f} en moyenne sur les {len(prior)} "
                f"derniers runs",
            ))
            continue
        stats = request_stats.get(source)
        ratio = stats.failure_ratio if stats else None
        if ratio is not None and ratio > guard.max_failed_ratio:
            found.append(SourceOutage(
                source, REQUESTS_FAILED,
                f"{_pct(ratio)} des requêtes en échec ({stats.failed}/{stats.attempted}, "
                f"seuil {_pct(guard.max_failed_ratio)})",
            ))
            continue
        boards_now = by_board.get(source) or {}
        boards_before = (previous.get("by_board") or {}).get(source) or {}
        down = sorted(
            board for board, n in boards_now.items()
            if int(n or 0) == 0
            and int(boards_before.get(board, 0) or 0) >= guard.board_min_previous
        )
        if down:
            detail = ", ".join(
                f"{board} ({int(boards_before.get(board, 0) or 0)} au run précédent)"
                for board in down
            )
            found.append(SourceOutage(
                source, BOARD_EMPTY,
                f"{len(down)} board(s) à 0 offre : {detail}",
                boards=tuple(down),
            ))
    return found


def closure_outage(
    source: str, checked: int, closed: int, guard: OutageGuardConfig
) -> SourceOutage | None:
    """Too many "gone" answers from one source at once: a dead API, not a hiring freeze."""
    if checked < guard.min_checked or checked == 0:
        return None
    ratio = closed / checked
    if ratio <= guard.max_closed_ratio:
        return None
    return SourceOutage(
        source, CLOSURES,
        f"{_pct(ratio)} des {checked} offres vérifiées annoncées fermées "
        f"(seuil {_pct(guard.max_closed_ratio)}, minimum {guard.min_checked} vérifiées)",
    )


def banner(outage: SourceOutage) -> str:
    """« <source> indisponible — clôtures suspendues » plus the reason, one line."""
    scope = "" if outage.whole_source else f" ({len(outage.boards)} board(s))"
    return f"{outage.label}{scope} indisponible — clôtures suspendues : {outage.reason}"
