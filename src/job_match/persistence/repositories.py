import json
import sqlite3
from datetime import UTC, date, datetime

from job_match.domain.models import (
    Article,
    Company,
    ContractType,
    Eligibility,
    ExperienceRequirement,
    ExperienceStatus,
    FundingEvent,
    Job,
    Lead,
    RawPayload,
    RunSummary,
    ScoreResult,
    ScoringBreakdown,
    WorkplaceType,
)
from job_match.normalization.company import normalize_company

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _dt(val: str | None) -> datetime | None:
    return datetime.fromisoformat(val) if val else None


def _score_result_to_dict(sr: ScoreResult) -> dict:
    return {
        "engine": sr.engine,
        "available": sr.available,
        "score": sr.score,
        "positive_matches": list(sr.positive_matches),
        "negative_matches": list(sr.negative_matches),
        "missing_preferences": list(sr.missing_preferences),
        "explanations": list(sr.explanations),
        "raw": sr.raw,
    }


def _score_result_from_dict(d: dict) -> ScoreResult:
    return ScoreResult(
        engine=d["engine"],
        available=d["available"],
        score=d.get("score"),
        positive_matches=tuple(d.get("positive_matches", [])),
        negative_matches=tuple(d.get("negative_matches", [])),
        missing_preferences=tuple(d.get("missing_preferences", [])),
        explanations=tuple(d.get("explanations", [])),
        raw=d.get("raw", {}),
    )


def _breakdown_to_json(bd: ScoringBreakdown) -> str:
    return json.dumps(
        {
            "eligible": bd.eligible,
            "experience": str(bd.experience),
            "score": bd.score,
            "positive_matches": list(bd.positive_matches),
            "negative_matches": list(bd.negative_matches),
            "missing_preferences": list(bd.missing_preferences),
            "explanations": list(bd.explanations),
            "engines": {k: _score_result_to_dict(v) for k, v in bd.engines.items()},
            "divergence": bd.divergence,
            "needs_review": bd.needs_review,
        }
    )


def _breakdown_from_json(text: str) -> ScoringBreakdown:
    d = json.loads(text)
    return ScoringBreakdown(
        eligible=d["eligible"],
        experience=ExperienceStatus(d["experience"]),
        score=d.get("score"),
        positive_matches=tuple(d.get("positive_matches", [])),
        negative_matches=tuple(d.get("negative_matches", [])),
        missing_preferences=tuple(d.get("missing_preferences", [])),
        explanations=tuple(d.get("explanations", [])),
        engines={k: _score_result_from_dict(v) for k, v in d.get("engines", {}).items()},
        divergence=d.get("divergence"),
        needs_review=d.get("needs_review", False),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_source(conn: sqlite3.Connection, source_id: str, kind: str = "job") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sources(id, kind, name) VALUES (?, ?, ?)",
        (source_id, kind, source_id),
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    exp: ExperienceRequirement | None = None
    if row["experience_status"] is not None:
        exp = ExperienceRequirement(
            status=ExperienceStatus(row["experience_status"]),
            min_years=row["experience_min"],
            max_years=row["experience_max"],
            evidence=row["experience_evidence"],
        )

    bd: ScoringBreakdown | None = None
    if row["scoring_breakdown"] is not None:
        bd = _breakdown_from_json(row["scoring_breakdown"])

    return Job(
        id=row["id"],
        source=row["source_id"],
        source_job_id=row["source_job_id"],
        title=row["title"],
        company=row["company"],
        company_id=row["company_id"],
        location=row["location"],
        workplace_type=WorkplaceType(row["workplace_type"]),
        contract_type=ContractType(row["contract_type"]),
        description=row["description"],
        url=row["url"],
        published_at=_dt(row["published_at"]),
        collected_at=datetime.fromisoformat(row["collected_at"]),
        fingerprint=row["fingerprint"],
        experience=exp,
        eligibility=Eligibility(row["eligibility"]) if row["eligibility"] else None,
        rejection_reason=row["rejection_reason"],
        score=row["score"],
        scoring_breakdown=bd,
    )


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------

class CompanyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, company: Company) -> Company:
        self._conn.execute(
            "INSERT OR IGNORE INTO companies(name, normalized_name, website, location)"
            " VALUES (?, ?, ?, ?)",
            (company.name, company.normalized_name, company.website, company.location),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id, name, normalized_name, website, location"
            " FROM companies WHERE normalized_name = ?",
            (company.normalized_name,),
        ).fetchone()
        return Company(
            id=row["id"],
            name=row["name"],
            normalized_name=row["normalized_name"],
            website=row["website"],
            location=row["location"],
        )

    def get_by_normalized(self, normalized_name: str) -> Company | None:
        row = self._conn.execute(
            "SELECT id, name, normalized_name, website, location"
            " FROM companies WHERE normalized_name = ?",
            (normalized_name,),
        ).fetchone()
        if row is None:
            return None
        return Company(
            id=row["id"],
            name=row["name"],
            normalized_name=row["normalized_name"],
            website=row["website"],
            location=row["location"],
        )


class RawPayloadRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, payload: RawPayload) -> None:
        _ensure_source(self._conn, payload.source)
        self._conn.execute(
            "INSERT OR IGNORE INTO raw_payloads"
            "(source_id, source_item_id, fetched_at, payload_json)"
            " VALUES (?, ?, ?, ?)",
            (
                payload.source,
                payload.source_id,
                payload.fetched_at.isoformat(),
                payload.payload_json,
            ),
        )
        self._conn.commit()


class JobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, job: Job) -> Job:
        _ensure_source(self._conn, job.source, "job")

        bd_json = _breakdown_to_json(job.scoring_breakdown) if job.scoring_breakdown else None
        needs_review = int(job.scoring_breakdown.needs_review) if job.scoring_breakdown else 0
        company_n = normalize_company(job.company)

        self._conn.execute(
            """
            INSERT INTO jobs(
                source_id, source_job_id, title, company, company_normalized, company_id,
                location, workplace_type, contract_type, description, url,
                published_at, collected_at, fingerprint,
                experience_min, experience_max, experience_status, experience_evidence,
                eligibility, rejection_reason, score, scoring_breakdown, needs_review
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, source_job_id) DO UPDATE SET
                title              = excluded.title,
                company            = excluded.company,
                company_normalized = excluded.company_normalized,
                company_id         = excluded.company_id,
                location           = excluded.location,
                workplace_type     = excluded.workplace_type,
                contract_type      = excluded.contract_type,
                description        = excluded.description,
                url                = excluded.url,
                published_at       = excluded.published_at,
                collected_at       = excluded.collected_at,
                fingerprint        = excluded.fingerprint,
                experience_min     = excluded.experience_min,
                experience_max     = excluded.experience_max,
                experience_status  = excluded.experience_status,
                experience_evidence= excluded.experience_evidence,
                eligibility        = excluded.eligibility,
                rejection_reason   = excluded.rejection_reason,
                score              = excluded.score,
                scoring_breakdown  = excluded.scoring_breakdown,
                needs_review       = excluded.needs_review
            """,
            (
                job.source,
                job.source_job_id,
                job.title,
                job.company,
                company_n,
                job.company_id,
                job.location,
                str(job.workplace_type),
                str(job.contract_type),
                job.description,
                job.url,
                job.published_at.isoformat() if job.published_at else None,
                job.collected_at.isoformat(),
                job.fingerprint,
                job.experience.min_years if job.experience else None,
                job.experience.max_years if job.experience else None,
                str(job.experience.status) if job.experience else None,
                job.experience.evidence if job.experience else None,
                str(job.eligibility) if job.eligibility else None,
                job.rejection_reason,
                job.score,
                bd_json,
                needs_review,
            ),
        )
        self._conn.commit()

        row = self._conn.execute(
            "SELECT id FROM jobs WHERE source_id = ? AND source_job_id = ?",
            (job.source, job.source_job_id),
        ).fetchone()
        # Return a new frozen Job with id set
        return Job(
            id=row["id"],
            source=job.source,
            source_job_id=job.source_job_id,
            title=job.title,
            company=job.company,
            company_id=job.company_id,
            location=job.location,
            workplace_type=job.workplace_type,
            contract_type=job.contract_type,
            description=job.description,
            url=job.url,
            published_at=job.published_at,
            collected_at=job.collected_at,
            fingerprint=job.fingerprint,
            experience=job.experience,
            eligibility=job.eligibility,
            rejection_reason=job.rejection_reason,
            score=job.score,
            scoring_breakdown=job.scoring_breakdown,
        )

    def get(self, job_id: int) -> Job | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row else None

    def list_eligible(self, min_score: int | None = None) -> list[Job]:
        if min_score is not None:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE eligibility = 'ELIGIBLE' AND score >= ?"
                " ORDER BY score DESC",
                (min_score,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE eligibility = 'ELIGIBLE' ORDER BY score DESC"
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_rejected(self) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE eligibility = 'REJECTED' ORDER BY collected_at DESC"
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def get_by_fingerprint(self, fingerprint: str) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_unnotified(self, strong_threshold: int | None = None) -> list[Job]:
        """Return canonical eligible jobs not yet notified, strong first then by score."""
        rows = self._conn.execute(
            """
            SELECT j.*
            FROM jobs j
            LEFT JOIN job_duplicates d ON d.duplicate_job_id = j.id
            WHERE j.eligibility = 'ELIGIBLE'
              AND j.notified_at IS NULL
              AND d.duplicate_job_id IS NULL
            ORDER BY j.score DESC, j.collected_at DESC
            """
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_notified(self, job_ids: list[int], notified_at: datetime) -> None:
        if not job_ids:
            return
        placeholders = ",".join("?" * len(job_ids))
        self._conn.execute(
            f"UPDATE jobs SET notified_at = ? WHERE id IN ({placeholders})",
            [notified_at.isoformat(), *job_ids],
        )
        self._conn.commit()

    def reset_notified_since(self, since: date) -> int:
        """Reset notified_at to NULL for eligible canonical jobs notified on or after `since`.

        Returns the number of rows updated.
        """
        since_iso = since.isoformat()  # "YYYY-MM-DD" — ISO sort order makes >= work on TEXT
        cursor = self._conn.execute(
            """
            UPDATE jobs
            SET notified_at = NULL
            WHERE eligibility = 'ELIGIBLE'
              AND notified_at >= ?
              AND id NOT IN (SELECT duplicate_job_id FROM job_duplicates)
            """,
            (since_iso,),
        )
        self._conn.commit()
        return cursor.rowcount

    def list_by_block(
        self,
        company_normalized: str,
        contract_type: ContractType,
        since: datetime,
    ) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE company_normalized = ? AND contract_type = ?"
            " AND collected_at >= ?",
            (company_normalized, str(contract_type), since.isoformat()),
        ).fetchall()
        return [_row_to_job(r) for r in rows]


class JobScoreRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, job_id: int, result: ScoreResult, scored_at: datetime | None = None) -> None:
        ts = (scored_at or datetime.now(UTC)).isoformat()
        self._conn.execute(
            """
            INSERT INTO job_scores(job_id, engine, available, score, result_json, scored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, engine) DO UPDATE SET
                available   = excluded.available,
                score       = excluded.score,
                result_json = excluded.result_json,
                scored_at   = excluded.scored_at
            """,
            (
                job_id,
                result.engine,
                int(result.available),
                result.score,
                json.dumps(_score_result_to_dict(result)),
                ts,
            ),
        )
        self._conn.commit()


class JobDuplicateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_link(
        self,
        canonical_id: int,
        duplicate_id: int,
        reason: str,
        similarity: float | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO job_duplicates"
            "(canonical_job_id, duplicate_job_id, reason, similarity, detected_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (canonical_id, duplicate_id, reason, similarity, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def get_canonical_id(self, job_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT canonical_job_id FROM job_duplicates WHERE duplicate_job_id = ?",
            (job_id,),
        ).fetchone()
        return row["canonical_job_id"] if row else None

    def list_duplicates_of(self, canonical_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT duplicate_job_id FROM job_duplicates WHERE canonical_job_id = ?",
            (canonical_id,),
        ).fetchall()
        return [r["duplicate_job_id"] for r in rows]


class RunRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(
        self,
        summary: RunSummary,
        started_at: datetime,
        finished_at: datetime | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs(pipeline, started_at, finished_at, summary_json) VALUES (?, ?, ?, ?)",
            (
                summary.pipeline,
                started_at.isoformat(),
                finished_at.isoformat() if finished_at else None,
                json.dumps(
                    {
                        "fetched": summary.fetched,
                        "normalized": summary.normalized,
                        "rejected_by_reason": summary.rejected_by_reason,
                        "duplicates": summary.duplicates,
                        "eligible": summary.eligible,
                        "strong": summary.strong,
                        "articles": summary.articles,
                        "leads": summary.leads,
                        "errors": summary.errors,
                        "api_calls": summary.api_calls,
                        "feeds": summary.feeds,
                        "funding_articles": summary.funding_articles,
                        "funding_events": summary.funding_events,
                        "funding_no_company": summary.funding_no_company,
                        "leads_deduped": summary.leads_deduped,
                        "by_source": summary.by_source,
                    }
                ),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Articles (funding pipeline)
# ---------------------------------------------------------------------------

def _row_to_article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        source=row["source_id"],
        url=row["url"],
        title=row["title"],
        collected_at=_dt(row["collected_at"]),  # type: ignore[arg-type]
        published_at=_dt(row["published_at"]),
        extract=row["extract"],
        is_funding=bool(row["is_funding"]),
        processed_at=_dt(row["processed_at"]),
    )


class ArticleRepository:
    """Articles are keyed by normalized URL. Only a short extract is stored."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def exists(self, url: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
        return row is not None

    def get_by_url(self, url: str) -> Article | None:
        row = self._conn.execute("SELECT * FROM articles WHERE url = ?", (url,)).fetchone()
        return _row_to_article(row) if row else None

    def get(self, article_id: int) -> Article | None:
        row = self._conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return _row_to_article(row) if row else None

    def save(self, article: Article) -> Article:
        """Insert a new article. An existing URL is left untouched (first seen wins)."""
        _ensure_source(self._conn, article.source, "funding")
        self._conn.execute(
            """
            INSERT OR IGNORE INTO articles
                (source_id, url, title, published_at, collected_at, extract,
                 is_funding, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.source,
                article.url,
                article.title,
                article.published_at.isoformat() if article.published_at else None,
                article.collected_at.isoformat(),
                article.extract,
                int(article.is_funding),
                article.processed_at.isoformat() if article.processed_at else None,
            ),
        )
        self._conn.commit()
        return self.get_by_url(article.url)  # type: ignore[return-value]

    def mark_processed(self, article_id: int, is_funding: bool, processed_at: datetime) -> None:
        self._conn.execute(
            "UPDATE articles SET is_funding = ?, processed_at = ? WHERE id = ?",
            (int(is_funding), processed_at.isoformat(), article_id),
        )
        self._conn.commit()

    def list_unprocessed(self, limit: int | None = None) -> list[Article]:
        sql = "SELECT * FROM articles WHERE processed_at IS NULL ORDER BY collected_at, id"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return [_row_to_article(r) for r in self._conn.execute(sql, params).fetchall()]

    def list_collected_since(self, since: date, limit: int | None = None) -> list[Article]:
        sql = "SELECT * FROM articles WHERE collected_at >= ? ORDER BY collected_at, id"
        params: tuple = (since.isoformat(),)
        if limit is not None:
            sql += " LIMIT ?"
            params = (since.isoformat(), limit)
        return [_row_to_article(r) for r in self._conn.execute(sql, params).fetchall()]

    def list_recent(self, limit: int = 50) -> list[Article]:
        rows = self._conn.execute(
            "SELECT * FROM articles ORDER BY collected_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_article(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


# ---------------------------------------------------------------------------
# Funding events / leads
# ---------------------------------------------------------------------------

_EVENT_SELECT = """
    SELECT fe.*, a.source_id AS a_source, a.url AS a_url
    FROM funding_events fe
    LEFT JOIN articles a ON a.id = fe.article_id
"""


def _row_to_event(row: sqlite3.Row) -> FundingEvent:
    investors = json.loads(row["investors_json"]) if row["investors_json"] else None
    evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else {}
    return FundingEvent(
        id=row["id"],
        company_id=row["company_id"],
        article_id=row["article_id"],
        source=row["a_source"] or "",
        article_url=row["a_url"] or "",
        collected_at=_dt(row["collected_at"]),  # type: ignore[arg-type]
        amount=row["amount"],
        currency=row["currency"],
        round=row["round"],
        date=row["event_date"],
        investors=tuple(investors) if investors is not None else None,
        sector=row["sector"],
        location=row["location"],
        recruiting_signal=row["recruiting_signal"],
        evidence=evidence,
    )


class FundingEventRepository:
    """One event per (article, company). Re-extraction updates the row in place."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, event: FundingEvent) -> FundingEvent:
        self._conn.execute(
            """
            INSERT INTO funding_events
                (company_id, article_id, amount, currency, round, event_date, investors_json,
                 sector, location, recruiting_signal, evidence_json, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id, company_id) DO UPDATE SET
                amount = excluded.amount,
                currency = excluded.currency,
                round = excluded.round,
                event_date = excluded.event_date,
                investors_json = excluded.investors_json,
                sector = excluded.sector,
                location = excluded.location,
                recruiting_signal = excluded.recruiting_signal,
                evidence_json = excluded.evidence_json,
                collected_at = excluded.collected_at
            """,
            (
                event.company_id,
                event.article_id,
                event.amount,
                event.currency,
                event.round,
                event.date,
                json.dumps(list(event.investors)) if event.investors is not None else None,
                event.sector,
                event.location,
                event.recruiting_signal,
                json.dumps(event.evidence, ensure_ascii=False) if event.evidence else None,
                event.collected_at.isoformat(),
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            _EVENT_SELECT + " WHERE fe.article_id IS ? AND fe.company_id = ?",
            (event.article_id, event.company_id),
        ).fetchone()
        return _row_to_event(row)

    def get(self, event_id: int) -> FundingEvent | None:
        row = self._conn.execute(_EVENT_SELECT + " WHERE fe.id = ?", (event_id,)).fetchone()
        return _row_to_event(row) if row else None

    def list_for_article(self, article_id: int) -> list[FundingEvent]:
        rows = self._conn.execute(
            _EVENT_SELECT + " WHERE fe.article_id = ? ORDER BY fe.id", (article_id,)
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def delete_for_article_except(self, article_id: int, keep_ids: list[int]) -> int:
        """Remove stale events (and their leads) for an article after re-extraction."""
        placeholders = ",".join("?" for _ in keep_ids) or "NULL"
        params: tuple = (article_id, *keep_ids)
        self._conn.execute(
            "DELETE FROM leads WHERE funding_event_id IN "
            f"(SELECT id FROM funding_events WHERE article_id = ? AND id NOT IN ({placeholders}))",
            params,
        )
        cur = self._conn.execute(
            f"DELETE FROM funding_events WHERE article_id = ? AND id NOT IN ({placeholders})",
            params,
        )
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM funding_events").fetchone()[0]


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        id=row["id"],
        company_id=row["company_id"],
        funding_event_id=row["funding_event_id"],
        reason=row["reason"],
        created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
        status=row["status"],
        notified_at=_dt(row["notified_at"]),
        priority=row["priority"],
    )


class LeadRepository:
    """One lead per funding event. Re-extraction only refreshes reason/priority."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, lead: Lead) -> Lead:
        self._conn.execute(
            """
            INSERT INTO leads (company_id, funding_event_id, reason, status, created_at,
                               notified_at, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(funding_event_id) DO UPDATE SET
                reason = excluded.reason,
                priority = excluded.priority
            """,
            (
                lead.company_id,
                lead.funding_event_id,
                lead.reason,
                lead.status,
                lead.created_at.isoformat(),
                lead.notified_at.isoformat() if lead.notified_at else None,
                lead.priority,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM leads WHERE funding_event_id = ?", (lead.funding_event_id,)
        ).fetchone()
        return _row_to_lead(row)

    def get(self, lead_id: int) -> Lead | None:
        row = self._conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return _row_to_lead(row) if row else None

    def get_for_event(self, funding_event_id: int) -> Lead | None:
        row = self._conn.execute(
            "SELECT * FROM leads WHERE funding_event_id = ?", (funding_event_id,)
        ).fetchone()
        return _row_to_lead(row) if row else None

    def has_recent(
        self, company_id: int, since: datetime, exclude_event_id: int | None = None
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM leads WHERE company_id = ? AND created_at >= ?"
            " AND (funding_event_id IS NULL OR funding_event_id IS NOT ?) LIMIT 1",
            (company_id, since.isoformat(), exclude_event_id),
        ).fetchone()
        return row is not None

    def list_all(self) -> list[Lead]:
        rows = self._conn.execute("SELECT * FROM leads ORDER BY created_at, id").fetchall()
        return [_row_to_lead(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
