import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from job_match.domain.models import RunSummary

_ROOT = Path(__file__).parent.parent.parent
_CONFIG = _ROOT / "config"
_DATA = _ROOT / "data"

_FT_VARS = ("FT_CLIENT_ID", "FT_CLIENT_SECRET")


def main() -> None:
    # Load .env without overriding env vars already set (CI secrets win).
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(prog="job-match", description="Job intelligence pipeline")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_p = sub.add_parser("run", help="Fetch and process jobs from France Travail")
    run_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="Maximum number of items to process")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Run the full pipeline but write nothing to the database")

    digest_p = sub.add_parser("digest", help="Send email digest of unnotified jobs")
    digest_p.add_argument(
        "--dry-run", action="store_true",
        help="Render HTML to data/digest_preview.html instead of sending",
    )

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "digest":
        _cmd_digest(args)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_digest(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, datetime

    from job_match.config.loader import load_settings
    from job_match.notification.digest import DigestData, render_html
    from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository

    settings = load_settings(_CONFIG / "settings.yaml")
    db_path = str(_DATA / "jobs.sqlite")

    with Database(path=db_path) as db:
        job_repo = JobRepository(db.conn)
        jobs = job_repo.list_unnotified()

    strong = tuple(j for j in jobs if j.score is not None and j.score >= settings.strong_threshold)
    eligible = tuple(j for j in jobs if j not in strong)

    data = DigestData(
        strong=strong,
        eligible=eligible,
        generated_at=datetime.now(UTC),
    )

    total = len(strong) + len(eligible)
    print(f"Digest: {total} unnotified jobs ({len(strong)} strong, {len(eligible)} eligible)")

    if args.dry_run:
        _DATA.mkdir(parents=True, exist_ok=True)
        preview = _DATA / "digest_preview.html"
        preview.write_text(render_html(data), encoding="utf-8")
        print(f"  [DRY RUN] HTML written to {preview}")
        return

    if total == 0:
        print("  No new jobs to send.")
        return

    try:
        notifier = EmailNotifier.from_env()
    except SmtpConfigError as exc:
        print(f"SMTP not configured: {exc}", file=sys.stderr)
        sys.exit(1)

    ok = notifier.send(data)
    if ok:
        with Database(path=db_path) as db:
            job_repo = JobRepository(db.conn)
            job_ids = [j.id for j in jobs if j.id is not None]
            job_repo.mark_notified(job_ids, datetime.now(UTC))
        print(f"  Sent. {total} jobs marked as notified.")
    else:
        print("  Send failed — see logs. Jobs not marked as notified.", file=sys.stderr)
        sys.exit(1)


def _cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.adapters.jobs.france_travail import FranceTravailSource
    from job_match.config.loader import load_aliases, load_profile, load_settings
    from job_match.persistence.db import Database
    from job_match.pipelines.jobs import run_jobs

    profile_path = _CONFIG / "profile.yaml"
    profile = load_profile(profile_path)
    settings = load_settings(_CONFIG / "settings.yaml")
    aliases = load_aliases(_CONFIG / "aliases.yaml")
    print(f"profile: {profile_path} (experience_years={profile.candidate.experience_years})")

    if not args.dry_run:
        _DATA.mkdir(parents=True, exist_ok=True)

    missing = [v for v in _FT_VARS if not os.environ.get(v)]
    if missing:
        for var in missing:
            print(f"Missing {var}: set it in .env or as an env var", file=sys.stderr)
        sys.exit(1)

    db_path = ":memory:" if args.dry_run else str(_DATA / "jobs.sqlite")
    source = FranceTravailSource(profile, requests_per_second=settings.ft_requests_per_second)

    with Database(path=db_path) as db:
        summary = run_jobs(
            source, profile, settings, db, aliases,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    _print_summary(summary, dry_run=args.dry_run)


def _print_summary(summary: RunSummary, *, dry_run: bool = False) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nJobs run complete{tag}")
    print(f"  fetched:    {summary.fetched}")
    print(f"  normalized: {summary.normalized}")
    print(f"  rejected:   {summary.rejected_jobs} jobs")  # unique jobs, not reason count
    if summary.rejected_by_reason:
        print("  reason breakdown (may sum > jobs; a job can fail multiple gates):")
        for reason, count in sorted(summary.rejected_by_reason.items()):
            print(f"    {reason}: {count}")
    print(f"  duplicates: {summary.duplicates}")
    print(f"  eligible:   {summary.eligible}")
    print(f"  strong:     {summary.strong}")
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
