import json
import sqlite3
from datetime import UTC, datetime

from job_match.domain.models import (
    Company,
    ContractType,
    Eligibility,
    ExperienceRequirement,
    ExperienceStatus,
    Job,
    RawPayload,
    RunSummary,
    ScoreResult,
    ScoringBreakdown,
    WorkplaceType,
)

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

        self._conn.execute(
            """
            INSERT INTO jobs(
                source_id, source_job_id, title, company, company_id, location,
                workplace_type, contract_type, description, url,
                published_at, collected_at, fingerprint,
                experience_min, experience_max, experience_status, experience_evidence,
                eligibility, rejection_reason, score, scoring_breakdown, needs_review
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, source_job_id) DO UPDATE SET
                title              = excluded.title,
                company            = excluded.company,
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
                    }
                ),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
