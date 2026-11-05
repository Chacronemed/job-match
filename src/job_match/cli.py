import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from job_match.domain.models import RunSummary
from job_match.ops.summary import (
    append_step_summary,
    digest_markdown,
    failure_markdown,
    funding_markdown,
    jobs_markdown,
)

_logger = logging.getLogger(__name__)


def _quiet_http_logs() -> None:
    """Keep httpx's request log above INFO.

    It prints the full URL, and for Jooble that URL carries the API key in its path
    (Adzuna puts credentials in the query string). `job-match run` output goes to a
    public Actions log, so the secret must never be written there. Errors still surface:
    adapters log their own aggregate line per query, with the URL redacted.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _config_dir() -> Path:
    """Config directory: $JOB_MATCH_CONFIG_DIR or ./config (relative to CWD)."""
    env = os.environ.get("JOB_MATCH_CONFIG_DIR")
    return Path(env) if env else Path("config")


def _data_dir() -> Path:
    """Data directory: $JOB_MATCH_DATA_DIR or ./data (relative to CWD)."""
    env = os.environ.get("JOB_MATCH_DATA_DIR")
    return Path(env) if env else Path("data")


def main() -> None:
    # Load .env without overriding env vars already set (CI secrets win).
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(prog="job-match", description="Job intelligence pipeline")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_p = sub.add_parser("run", help="Fetch and process jobs from France Travail")
    run_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="Maximum offers per keyword x department query "
                            "(not a global cap: every query still runs)")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Run the full pipeline but write nothing to the database")

    rep_p = sub.add_parser(
        "reprocess",
        help="Re-apply the gate and scorer to jobs already in the DB (no API calls)",
    )
    rep_p.add_argument("--since", metavar="YYYY-MM-DD",
                       help="Only jobs collected on or after this date")
    rep_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="Show at most N top strong titles (0 for none; default 10)")
    rep_p.add_argument("--dry-run", action="store_true",
                       help="Report what would change without writing to the database")

    digest_p = sub.add_parser("digest", help="Send email digest of unnotified jobs")
    digest_p.add_argument(
        "--dry-run", action="store_true",
        help="Render HTML to data/digest_preview.html instead of sending",
    )
    digest_p.add_argument(
        "--resend-since", metavar="YYYY-MM-DD",
        help="Reset notified flag for jobs notified on or after this date, then send normally",
    )

    dash_p = sub.add_parser(
        "dashboard", help="Write the static dashboard (index.html + data.json) from the DB",
    )
    dash_p.add_argument("--out", default="site", metavar="DIR",
                        help="Output directory (default: site)")
    dash_p.add_argument("--no-ai-profile", action="store_true",
                        help="Do not write ai-profile.json (the anonymous skills summary "
                             "the Worker's AI rerank reads)")

    export_p = sub.add_parser(
        "export", help="Write the day's strongest matches for a companion tool (career-ops)",
    )
    export_p.add_argument("--top", type=int, default=3, metavar="N",
                          help="How many jobs, best score first (default: 3)")
    export_p.add_argument("--days", type=int, default=1, metavar="D",
                          help="Only jobs collected in the last D days (default: 1)")
    export_p.add_argument("--format", choices=["career-ops"], default="career-ops",
                          help="Target tool (default: career-ops, its data/pipeline.md format)")
    export_p.add_argument("--out", metavar="FILE",
                          help="File to write (default: data/export/career-ops-<date>.md)")
    export_p.add_argument("--append", metavar="PIPELINE_MD",
                          help="Instead of --out, add the lines under the Pending heading of "
                               "career-ops' own data/pipeline.md, skipping URLs it already has")

    ai_p = sub.add_parser(
        "ai-report",
        help="Weekly AI vs Python disagreements + my Tri verdicts -> a correction prompt "
             "(local file, never applied)",
    )
    ai_p.add_argument("--since", metavar="YYYY-MM-DD",
                      help="Disagreements recorded on/after this date (default: 7 days ago)")
    ai_p.add_argument("--out", metavar="PATH",
                      help="Report file (default: data/ai-report-<date>.md)")

    cal_p = sub.add_parser(
        "calibrate",
        help="Compare dashboard verdicts with scores; suggests changes, never applies them",
    )
    cal_p.add_argument("--since", metavar="YYYY-MM-DD",
                       help="Only verdicts given on/after this date")

    ops_p = sub.add_parser("ops", help="Operations: the silent-source alert")
    ops_sub = ops_p.add_subparsers(dest="ops_command", metavar="SUBCOMMAND")
    check_p = ops_sub.add_parser(
        "check-sources",
        help="Email an alert when a source returned 0 results N days in a row (never fails)",
    )
    check_p.add_argument("--days", type=int, default=3, metavar="N",
                         help="Consecutive runs with 0 results that trigger the alert (default: 3)")

    companies_p = sub.add_parser(
        "companies", help="Target companies (config/companies.yaml): which ATS serves them"
    )
    companies_sub = companies_p.add_subparsers(dest="companies_command", metavar="SUBCOMMAND")
    detect_p = companies_sub.add_parser(
        "detect",
        help="Check each company's real ATS and board id on the public endpoints; print a report",
    )
    detect_p.add_argument("--only", metavar="NAME", action="append",
                          help="Only this company (repeatable; case-insensitive)")
    detect_p.add_argument("--out", metavar="PATH", type=Path,
                          help="Also write the results as YAML (config/companies_detected.yaml)")
    detect_p.add_argument("--report", metavar="PATH", type=Path,
                          help="Also write the Markdown report to this file")

    tracking_p = sub.add_parser("tracking", help="Application tracking mirror (D1 -> jobs DB)")
    tracking_sub = tracking_p.add_subparsers(dest="tracking_command", metavar="SUBCOMMAND")
    timp_p = tracking_sub.add_parser(
        "import", help="Replace the local mirror with `wrangler d1 execute --json` exports",
    )
    timp_p.add_argument("--applications", required=True, metavar="PATH",
                        help="Export of SELECT * FROM applications")
    timp_p.add_argument("--decisions", required=True, metavar="PATH",
                        help="Export of SELECT * FROM decisions")
    timp_p.add_argument("--skill-overrides", metavar="PATH",
                        help="Export of SELECT * FROM skill_overrides "
                             "(default: keep the current mirror)")
    timp_p.add_argument("--ai-verdicts", metavar="PATH",
                        help="Export of SELECT * FROM ai_verdicts (with --ai-usage and "
                             "--disagreements; default: keep the current AI mirror)")
    timp_p.add_argument("--ai-usage", metavar="PATH", help="Export of SELECT * FROM ai_usage")
    timp_p.add_argument("--disagreements", metavar="PATH",
                        help="Export of SELECT * FROM disagreements")
    timp_p.add_argument("--ai-runs", metavar="PATH", help="Export of SELECT * FROM ai_runs")

    funding_p = sub.add_parser("funding", help="Funding / news pipeline")
    funding_sub = funding_p.add_subparsers(dest="funding_command", metavar="SUBCOMMAND")
    frun_p = funding_sub.add_parser("run", help="Ingest articles from RSS feeds")
    frun_p.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of feed entries to process")
    frun_p.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but write nothing to the database")
    frep_p = funding_sub.add_parser(
        "reprocess", help="Refetch stored articles and (re)run funding extraction",
    )
    frep_p.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Re-extract every article collected on/after this date "
                             "(default: only articles never processed)")
    frep_p.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of articles to reprocess")
    frep_p.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but write nothing to the database")

    cv_p = sub.add_parser("cv", help="Master CV for the application documents (private/)")
    cv_sub = cv_p.add_subparsers(dest="cv_command", metavar="SUBCOMMAND")
    cv_sub.add_parser("validate", help="Check private/cv_master.yaml and contact.yaml")
    cvpush_p = cv_sub.add_parser(
        "push", help="Validate, then upload both as private JSON objects to R2 (wrangler)",
    )
    cvpush_p.add_argument("--local", action="store_true",
                          help="Target the local R2 of `wrangler dev` (smoke test)")

    apply_p = sub.add_parser(
        "apply",
        help="Open an offer's application form, fill it from the kit; never sends (ADR 0023)",
    )
    apply_p.add_argument("job_key", nargs="?",
                         help="The offer's key (optional: without it, a numbered list of the"
                              " « À candidater » offers with a supported form)")
    apply_p.add_argument("--sent", action="store_true",
                         help="I sent it: status « Envoyée », follow-up date, documents version")
    apply_p.add_argument("--follow-up-days", type=int, default=7,
                         help="Follow-up date after --sent, in days (default 7)")
    apply_p.add_argument("--url", help="The application page, when the jobs DB has another one")

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "reprocess":
        _cmd_reprocess(args)
    elif args.command == "digest":
        _cmd_digest(args)
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "calibrate":
        _cmd_calibrate(args)
    elif args.command == "ai-report":
        _cmd_ai_report(args)
    elif args.command == "ops":
        if args.ops_command == "check-sources":
            _cmd_check_sources(args)
        else:
            ops_p.print_help()
            sys.exit(1)
    elif args.command == "companies":
        if args.companies_command == "detect":
            _cmd_companies_detect(args)
        else:
            companies_p.print_help()
            sys.exit(1)
    elif args.command == "tracking":
        if args.tracking_command == "import":
            _cmd_tracking_import(args)
        else:
            tracking_p.print_help()
            sys.exit(1)
    elif args.command == "funding":
        if args.funding_command == "run":
            _cmd_funding_run(args)
        elif args.funding_command == "reprocess":
            _cmd_funding_reprocess(args)
        else:
            funding_p.print_help()
            sys.exit(1)
    elif args.command == "apply":
        _cmd_apply(args)
    elif args.command == "cv":
        if args.cv_command == "validate":
            _cmd_cv_validate(args)
        elif args.cv_command == "push":
            _cmd_cv_push(args)
        else:
            cv_p.print_help()
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


def _load_master_or_exit():
    """The validated master and contact, or exit 1. Prints counts and error lines only:
    never a bullet, never a contact value."""
    from job_match.config.loader import (
        ConfigError,
        load_aliases,
        load_profile,
        load_settings,
        load_skill_vocabulary,
    )
    from job_match.documents.master import load_contact, load_master
    from job_match.documents.push import private_dir
    from job_match.documents.validate import validate_master

    cfg = _config_dir()
    priv = private_dir()
    try:
        settings = load_settings(cfg / "settings.yaml")
        master = load_master(priv / "cv_master.yaml")
        contact = load_contact(priv / "contact.yaml")
        from job_match.apply.config import load_apply

        load_apply(priv / "apply.yaml")
    except ConfigError as exc:
        print(f"cv: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        profile_skills = tuple(s.name for s in load_profile(cfg / "profile.yaml").skills.preferred)
    except ConfigError:
        profile_skills = ()
    errors = validate_master(
        master, contact, settings.documents,
        load_skill_vocabulary(cfg / "skill_vocabulary.yaml"), load_aliases(cfg / "aliases.yaml"),
        profile_skills,
    )
    n_bullets = len(master.bullets())
    print(
        f"cv: {len(master.experiences)} experiences, {len(master.projects)} projects, "
        f"{n_bullets} bullets, {len(master.skills)} skills, {len(errors)} errors"
    )
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    if errors:
        sys.exit(1)
    return master, contact


def _cmd_cv_validate(args: argparse.Namespace) -> None:
    _load_master_or_exit()


def _cmd_cv_push(args: argparse.Namespace) -> None:
    """Local only, by hand: the master and the contact leave this machine for R2 and nowhere
    else. Never wired into a workflow."""
    _quiet_http_logs()
    from job_match.apply import config as apply_config
    from job_match.documents.master import to_json
    from job_match.documents.push import (
        CONTACT_KEY,
        MASTER_KEY,
        PushError,
        private_dir,
        push_objects,
    )

    master, contact = _load_master_or_exit()
    objects = {MASTER_KEY: to_json(master), CONTACT_KEY: to_json(contact)}
    apply_path = private_dir() / "apply.yaml"
    if apply_path.exists():  # the kit's fixed answers and salary rule (ADR 0023)
        objects[apply_config.APPLY_KEY] = apply_config.to_json(apply_config.load_apply(apply_path))
    try:
        sizes = push_objects(objects, local=args.local)
    except PushError as exc:
        print(f"cv push failed: {exc}", file=sys.stderr)
        sys.exit(1)
    for key, n in sizes.items():
        print(f"  {key}: {n} bytes -> R2 {'local' if args.local else 'remote'}")


def _pick_application() -> str | None:
    """The numbered list of `job-match apply` without a key; the key of the number I type."""
    from job_match.apply import picker, remote

    try:
        apps = remote.kept_applications()
    except remote.RemoteError as exc:
        print(f"apply: applications not reachable ({exc})", file=sys.stderr)
        return None
    keys = [str(a["job_key"]) for a in apps]
    listing = picker.build(apps, picker.local_offers(_data_dir() / "jobs.sqlite", keys))
    if not listing.choices:
        print("Aucune candidature « À candidater » avec un formulaire pris en charge"
              " (Greenhouse, Lever, Ashby).")
        for line in picker.lines(listing)[len(listing.choices):]:
            print(line)
        return None
    for line in picker.lines(listing):
        print(line)
    for _ in range(3):
        try:
            answer = input(f"Numéro (1-{len(listing.choices)}) : ")
        except EOFError:
            return None
        choice = picker.pick(listing, answer)
        if choice is not None:
            print(f"→ {choice.title} · {choice.company}")
            return choice.key
        print("Numéro inconnu.")
    return None


def _cmd_apply(args: argparse.Namespace) -> None:
    """Local only (ADR 0023): fill the form, never send it. Prints labels and sources, never a
    value; nothing personal goes to a log."""
    _quiet_http_logs()
    from datetime import UTC, date, timedelta

    from job_match.apply import remote, session
    from job_match.apply.config import load_apply
    from job_match.apply.questions import load_questions
    from job_match.config.schema import ConfigError
    from job_match.documents.master import load_contact, load_master, to_json
    from job_match.documents.push import private_dir
    from job_match.tracking.constants import JOB_KEY_RE

    key = args.job_key
    if key is None:
        key = _pick_application()
        if key is None:
            sys.exit(1)
    if not JOB_KEY_RE.match(key):
        print(f"apply: invalid job key {key!r}", file=sys.stderr)
        sys.exit(2)
    if args.sent:
        today = date.today()
        follow = today + timedelta(days=max(1, args.follow_up_days))
        try:
            version = remote.latest_ready_version(key)
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            remote.mark_sent(key, today, follow, version, stamp)
        except remote.RemoteError as exc:
            print(f"apply --sent failed: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Envoyée le {today.isoformat()}, relance le {follow.isoformat()}, "
              + (f"documents v{version}." if version else "sans version de documents prête."))
        return

    priv = private_dir()
    try:
        questions = load_questions(_config_dir() / "apply_questions.yaml")
        apply_cfg = load_apply(priv / "apply.yaml")
        contact = load_contact(priv / "contact.yaml")
        master = load_master(priv / "cv_master.yaml")
    except ConfigError as exc:
        print(f"apply: {exc}", file=sys.stderr)
        sys.exit(1)
    offer = None
    db_path = _data_dir() / "jobs.sqlite"
    if db_path.exists():
        offer = session.find_offer(db_path, key)
    url = args.url or (offer.url if offer else None)
    if not url:
        print("apply: offer not in the jobs DB; pass --url", file=sys.stderr)
        sys.exit(1)

    paths = None
    try:
        version = remote.latest_ready_version(key)
        content = remote.fetch_content(key, version) if version else None
    except remote.RemoteError as exc:
        print(f"apply: documents not reachable ({exc}): contact fields only.", file=sys.stderr)
        content = None
    if content:
        import json as _json

        from job_match.apply.config import to_json as apply_json

        bundle = {"content": content, "master": _json.loads(to_json(master)),
                  "contact": _json.loads(to_json(contact)),
                  "apply": _json.loads(apply_json(apply_cfg))}
        out_dir = priv / "out" / "apply" / session.safe_dir_name(key)
        try:
            paths = session.render_local(bundle, out_dir, offer.location if offer else "")
        except RuntimeError as exc:
            print(f"apply: {exc}: no CV nor letter attached.", file=sys.stderr)
        else:
            print(f"Documents v{version} rendus dans {out_dir}")
    else:
        print("Pas de documents prêts pour cette offre : CV, lettre et kit non joints.")
    contact_dict = _json_contact(contact)
    inputs = session.load_inputs(paths, contact_dict, apply_cfg)

    pw, ctx, page = session.launch(priv / "browser-profile")
    try:
        report = session.fill_page(page, url, questions, inputs, session.wait_stdin,
                                   session.say_stdout)
        if report is not None:
            print("Rien n'est envoyé : relis, complète les champs surlignés et envoie toi-même.")
        print(f"Après l'envoi : job-match apply {key} --sent")
        session.wait_stdin("Entrée pour fermer le navigateur… ")
    finally:
        ctx.close()
        pw.stop()


def _json_contact(contact) -> dict:
    from dataclasses import asdict

    return asdict(contact)


def _cmd_reprocess(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _quiet_http_logs()

    from datetime import UTC, datetime

    from job_match.config.loader import (
        load_aliases,
        load_profile,
        load_settings,
        load_skill_vocabulary,
    )
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository
    from job_match.pipelines.jobs import reprocess_jobs

    cfg = _config_dir()
    data_dir = _data_dir()
    profile = load_profile(cfg / "profile.yaml")
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    vocabulary = load_skill_vocabulary(cfg / "skill_vocabulary.yaml")

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            sys.exit(1)

    db_path = data_dir / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)

    with Database(path=str(db_path)) as db:
        profile = _with_skill_overrides(profile, settings, db)
        summary = reprocess_jobs(
            profile, settings, db, aliases,
            since=since, dry_run=args.dry_run, vocabulary=vocabulary,
        )
        top = JobRepository(db.conn).list_eligible(min_score=settings.strong_threshold)

    _print_reprocess_summary(summary, top, limit=args.limit, dry_run=args.dry_run)


def _print_reprocess_summary(
    summary: RunSummary, top: list, *, limit: int | None, dry_run: bool
) -> None:
    """Aggregate counts, then the N best scores.

    `--limit 0` prints the counts alone: the daily workflow runs this step in a public
    Actions log, where individual postings have no business being.
    """
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nReprocess complete{tag}")
    print(f"  jobs read:  {summary.fetched}")
    print(f"  rejected:   {summary.rejected_jobs} jobs")
    if summary.rejected_by_reason:
        print("  reason breakdown (may sum > jobs; a job can fail multiple gates):")
        for reason, count in sorted(summary.rejected_by_reason.items()):
            print(f"    {reason}: {count}")
    print(f"  eligible:   {summary.eligible}")
    print(f"  strong:     {summary.strong}")
    print(f"  stretch:    {summary.stretch}  (experience within stretch_years; never strong)")
    if summary.rqth_recruiter:
        print(
            f"  RQTH recruiter offers: {summary.rqth_recruiter}"
            f" (end client named: {summary.rqth_end_client})"
        )
    print(f"  new duplicate links: {summary.duplicates}")
    print(f"  links removed:       {summary.stale_links_dropped}  (rules no longer match)")
    if summary.self_links_dropped:
        print(f"  self-links dropped:  {summary.self_links_dropped}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
    if summary.by_department:
        _print_top_departments(summary.by_department)

    n = 10 if limit is None else limit
    if top and n > 0:
        print(f"\n  top {min(n, len(top))} strong titles:")
        for job in top[:n]:
            print(f"    {job.score:>3}  {job.title}  —  {job.company}")


def _cmd_digest(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, date, datetime

    from job_match.config.loader import load_settings
    from job_match.notification.assemble import build_digest
    from job_match.notification.digest import render_html
    from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository, LeadRepository

    cfg = _config_dir()
    data_dir = _data_dir()
    settings = load_settings(cfg / "settings.yaml")
    db_path = str(data_dir / "jobs.sqlite")

    if args.resend_since:
        try:
            since = date.fromisoformat(args.resend_since)
        except ValueError:
            print(
                f"Invalid date {args.resend_since!r} — expected YYYY-MM-DD",
                file=sys.stderr,
            )
            sys.exit(1)
        with Database(path=db_path) as db:
            n_jobs = JobRepository(db.conn).reset_notified_since(since)
            n_leads = LeadRepository(db.conn).reset_notified_since(since)
        print(f"  Reset notified_at for {n_jobs} job(s) and {n_leads} lead(s) since {since}")

    with Database(path=db_path) as db:
        batch = build_digest(db, settings, datetime.now(UTC))
    data = batch.data

    print(
        f"Digest: {len(batch.job_ids)} unnotified jobs ({len(data.strong)} strong, "
        f"{len(data.eligible)} eligible, {len(data.stretch)} stretch), "
        f"{len(batch.lead_ids)} funding leads, {len(data.followups)} follow-ups due"
    )
    print(
        f"  held back (stay unnotified): {batch.jobs_below_min_score} jobs below "
        f"min_score {settings.digest.min_score}; leads filtered "
        f"{dict(sorted(batch.leads_filtered.items())) or '{}'}, "
        f"{batch.leads_overflow} over max_leads {settings.digest.max_leads}"
    )

    if args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)
        preview = data_dir / "digest_preview.html"
        preview.write_text(render_html(data), encoding="utf-8")
        print(f"  [DRY RUN] HTML written to {preview}")
        return

    if batch.is_empty:
        print("  No new jobs, leads or follow-ups to send.")
        append_step_summary(digest_markdown(jobs=0, strong=0, leads=0, followups=0, sent=False))
        return

    try:
        notifier = EmailNotifier.from_env()
    except SmtpConfigError as exc:
        print(f"SMTP not configured: {exc}", file=sys.stderr)
        sys.exit(1)

    if not notifier.send(data):
        print("  Send failed — see logs. Nothing marked as notified.", file=sys.stderr)
        sys.exit(1)

    # Mark only after a successful send, so a failed send is retried next run.
    sent_at = datetime.now(UTC)
    with Database(path=db_path) as db:
        JobRepository(db.conn).mark_notified(list(batch.job_ids), sent_at)
        LeadRepository(db.conn).mark_notified(list(batch.lead_ids), sent_at)
    print(f"  Sent. {len(batch.job_ids)} jobs and {len(batch.lead_ids)} leads marked as notified.")
    append_step_summary(digest_markdown(
        jobs=len(batch.job_ids), strong=len(data.strong), leads=len(batch.lead_ids),
        followups=len(data.followups), sent=True,
    ))


def _cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _quiet_http_logs()

    from job_match.adapters.jobs.factory import build_sources, missing_env
    from job_match.config.loader import (
        load_aliases,
        load_ats_boards,
        load_profile,
        load_settings,
        load_skill_vocabulary,
    )
    from job_match.persistence.db import Database
    from job_match.pipelines.jobs import run_jobs

    cfg = _config_dir()
    data_dir = _data_dir()
    profile_path = cfg / "profile.yaml"
    profile = load_profile(profile_path)
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    vocabulary = load_skill_vocabulary(cfg / "skill_vocabulary.yaml")
    print(f"profile: {profile_path} (experience_years={profile.candidate.experience_years})")

    if not args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)

    # Each enabled source with credentials runs; the others are skipped with a warning
    # inside build_sources. Only an empty result is fatal.
    sources = build_sources(
        profile, settings, limit=args.limit,
        ats_boards=load_ats_boards(cfg / "ats_boards.yaml"),
    )
    if not sources:
        print("No job source could run. Missing credentials:", file=sys.stderr)
        for name in settings.sources.enabled:
            for var in missing_env(name):
                print(f"  {name}: {var}", file=sys.stderr)
        print("Set them in .env or as env vars (see .env.example).", file=sys.stderr)
        sys.exit(1)
    print(f"sources: {', '.join(s.name for s in sources)}")

    db_path = ":memory:" if args.dry_run else str(data_dir / "jobs.sqlite")

    # A dry run reads an empty in-memory DB, so it runs without the skill overrides.
    started = time.perf_counter()
    try:
        with Database(path=db_path) as db:
            profile = _with_skill_overrides(profile, settings, db)
            summary = run_jobs(
                sources, profile, settings, db, aliases,
                dry_run=args.dry_run, vocabulary=vocabulary,
            )
    except Exception as exc:
        _fail_loudly("Jobs run", exc)
        raise

    _print_summary(summary, dry_run=args.dry_run)
    append_step_summary(jobs_markdown(summary, time.perf_counter() - started))


def _fail_loudly(step: str, exc: BaseException) -> None:
    """The job summary and an Actions error annotation say what failed; the exit code
    (the re-raise) turns the step red. The traceback goes to the log as usual."""
    append_step_summary(failure_markdown(step, exc))
    print(f"::error title={step} failed::{type(exc).__name__}: {exc}")


def _cmd_companies_detect(args: argparse.Namespace) -> None:
    """`job-match companies detect`: the real ATS of each target company (M28). Network
    reads of public endpoints only; prints the Markdown report, writes nothing by default."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    _quiet_http_logs()
    for stream in (sys.stdout, sys.stderr):  # a Windows console is cp1252: « ✓ », « → »
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    from job_match.companies.detect import Detector, detect_all
    from job_match.companies.report import render_report, write_record
    from job_match.config.loader import ConfigError, load_companies

    try:
        companies = load_companies(_config_dir() / "companies.yaml")
    except ConfigError as exc:
        print(f"companies.yaml: {exc}", file=sys.stderr)
        sys.exit(1)
    every_name = [c.name for c in companies]
    if args.only:
        wanted = {n.lower() for n in args.only}
        companies = [c for c in companies if c.name.lower() in wanted]
    if not companies:
        print("No company to check.")
        return

    def progress(i: int, found) -> None:
        print(f"[{i}/{len(companies)}] {found.company}: {found.status} "
              f"{found.ats or found.platform or ''}", file=sys.stderr)

    detector = Detector()
    try:
        results = detect_all(companies, detector, progress=progress)
    finally:
        detector.close()
    report = render_report(results, requests=detector.requests)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    if args.out:
        # `--only` re-checks a few companies: their entries are replaced, the rest kept.
        write_record(results, args.out, datetime.now().astimezone(),
                     merge_into=every_name if args.only else None)
        print(f"Written: {args.out}", file=sys.stderr)


def _cmd_check_sources(args: argparse.Namespace) -> None:
    """`job-match ops check-sources`: alert on a source silent for N runs. Exit 0 always."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError
    from job_match.ops.summary import alert_text, silent_sources
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import RunRepository

    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: nothing to check.")
        return
    with Database(path=str(db_path)) as db:
        runs = RunRepository(db.conn).list_recent(("jobs",), limit=args.days)
    names = silent_sources(runs, days=args.days)
    if not names:
        print(f"Sources: none silent for {args.days} runs.")
        return
    subject, body = alert_text(names, args.days)
    print(f"ALERT: {subject}")
    print(f"::warning title=Silent source::{subject}")
    append_step_summary(f"## ⚠️ Silent source\n\n{subject}")
    try:
        sent = EmailNotifier.from_env().send_text(subject, body)
    except SmtpConfigError as exc:
        print(f"  alert not emailed, SMTP not configured: {exc}", file=sys.stderr)
        return
    print("  alert emailed." if sent else "  alert email failed (see log).")


def _build_funding_sources(names: list[str]) -> list:
    from job_match.adapters.funding.frenchweb import FrenchWebSource
    from job_match.adapters.funding.maddyness import MaddynessSource

    registry = {"maddyness": MaddynessSource, "frenchweb": FrenchWebSource}
    sources = []
    for name in names:
        cls = registry.get(name)
        if cls is None:
            print(f"Unknown funding source {name!r} in settings.yaml "
                  f"(known: {', '.join(sorted(registry))})", file=sys.stderr)
            sys.exit(1)
        sources.append(cls())
    return sources


def _cmd_tracking_import(args: argparse.Namespace) -> None:
    """Mirror the D1 tracking tables. Prints counts only: notes and links are private and
    the CI log is public."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.config.loader import load_skill_vocabulary
    from job_match.persistence.db import Database
    from job_match.tracking.mirror import MirrorFormatError, import_ai, import_tracking

    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    overrides_arg = getattr(args, "skill_overrides", None)
    overrides_path = Path(overrides_arg) if overrides_arg else None
    ai_args = [getattr(args, k, None)
               for k in ("ai_verdicts", "ai_usage", "disagreements", "ai_runs")]
    if any(ai_args) and not all(ai_args):
        print("--ai-verdicts, --ai-usage, --disagreements and --ai-runs go together.",
              file=sys.stderr)
        sys.exit(2)
    vocabulary = load_skill_vocabulary(_config_dir() / "skill_vocabulary.yaml")
    with Database(path=str(db_path)) as db:
        try:
            result = import_tracking(
                db.conn, Path(args.applications), Path(args.decisions),
                overrides_path, vocabulary,
            )
        except MirrorFormatError as exc:
            print(f"Tracking export rejected ({exc}); previous mirror kept.", file=sys.stderr)
            sys.exit(1)
        ai_result = None
        if all(ai_args):
            try:
                ai_result = import_ai(db.conn, *(Path(a) for a in ai_args))
            except MirrorFormatError as exc:
                print(f"AI export rejected ({exc}); previous AI mirror kept.", file=sys.stderr)
    print(
        f"Tracking mirror: {result.applications} applications, {result.decisions} decisions,"
        f" {result.skill_overrides} skill overrides"
        f"{' (changed)' if result.overrides_changed else ''},"
        f" {result.skipped} invalid rows skipped"
    )
    if ai_result is not None:
        print(
            f"AI mirror: {ai_result.verdicts} verdicts, {ai_result.usage} usage rows,"
            f" {ai_result.disagreements} disagreements, {ai_result.runs} runs,"
            f" {ai_result.skipped} invalid rows skipped"
        )
    # The daily workflow reprocesses stored jobs only when the overrides changed.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            changed = "true" if result.overrides_changed else "false"
            fh.write(f"overrides_changed={changed}\n")


def _cmd_calibrate(args: argparse.Namespace) -> None:
    """Local only: the report names skills, so it never runs in the public CI log."""
    from datetime import date

    from job_match.calibration.report import DecidedJob, build_report, format_report
    from job_match.config.loader import load_settings
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import ApplicationRepository

    since = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            sys.exit(1)
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    settings = load_settings(_config_dir() / "settings.yaml")
    with Database(path=str(db_path)) as db:
        decided = ApplicationRepository(db.conn).list_latest_decisions(since)
    rows = [
        DecidedJob(
            label=label,
            score=score,
            positive=bd.positive_matches if bd else (),
            negative=bd.negative_matches if bd else (),
            unlisted=tuple(bd.unlisted) if bd else (),
        )
        for label, score, bd in decided
    ]
    print(format_report(build_report(rows, settings.strong_threshold)))


def _with_skill_overrides(profile, settings, db):
    """The profile plus the mirrored "je maîtrise" skills. Logs the count, never names."""
    from job_match.config.loader import apply_skill_overrides
    from job_match.persistence.repositories import ApplicationRepository

    overrides = ApplicationRepository(db.conn).list_skill_overrides()
    if overrides:
        print(f"skill overrides: {len(overrides)}")
    return apply_skill_overrides(profile, overrides, settings.scoring.override_weight)


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Write the static dashboard. Prints counts only: the CI log is public."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, datetime

    from job_match.config.loader import load_settings
    from job_match.dashboard.data import build_dashboard_data
    from job_match.dashboard.render import write_site
    from job_match.persistence.db import Database

    settings = load_settings(_config_dir() / "settings.yaml")
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)

    with Database(path=str(db_path)) as db:
        data = build_dashboard_data(db, settings, datetime.now(UTC))
    write_site(data, Path(args.out), _ai_profile(args))

    by_section = {s: 0 for s in ("strong", "eligible", "stretch")}
    for job in data["jobs"]:
        by_section[job["section"]] += 1
    print(
        f"Dashboard: {len(data['jobs'])} jobs ({by_section['strong']} strong, "
        f"{by_section['eligible']} eligible, {by_section['stretch']} stretch), "
        f"{len(data['leads'])} leads, {len(data['runs'])} runs -> {args.out}"
    )


def _cmd_export(args: argparse.Namespace, now: datetime | None = None) -> None:
    """Top matches of the day for career-ops. Prints counts and the path only."""
    from datetime import UTC

    from job_match.config.loader import load_settings
    from job_match.export.career_ops import append_to_inbox, select_top, write_inbox
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository

    settings = load_settings(_config_dir() / "settings.yaml")
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    now = now or datetime.now(UTC)
    with Database(path=str(db_path)) as db:
        jobs = JobRepository(db.conn).list_canonical_scored(
            now=now, max_age_days=settings.jobs.max_age_days
        )
    lines = select_top(jobs, top=args.top, now=now, days=args.days)
    if args.append:
        added = append_to_inbox(lines, Path(args.append))
        print(f"career-ops: {added} new of {len(lines)} selected -> {args.append}")
        return
    out = Path(args.out) if args.out else _data_dir() / "export" / f"career-ops-{now.date()}.md"
    write_inbox(lines, out)
    print(f"career-ops: {len(lines)} jobs (top {args.top}, last {args.days} day(s)) -> {out}")
    if not lines:
        print("  nothing collected in that window: widen --days or run `job-match run` first")


def _ai_profile(args: argparse.Namespace) -> dict | None:
    """The anonymous skills summary for the Worker's AI rerank, when a profile is at hand
    (config/profile.yaml or PROFILE_YAML). None keeps the summary off the site."""
    if getattr(args, "no_ai_profile", False):
        return None
    from job_match.ai.summary import skills_summary
    from job_match.config.loader import ConfigError, load_profile

    try:
        return skills_summary(load_profile(_config_dir() / "profile.yaml"))
    except ConfigError:
        print("No profile: ai-profile.json not written, the AI rerank will skip the day.")
        return None


def _cmd_ai_report(args: argparse.Namespace) -> None:
    """Local only: the report names offers and skills, so it never runs in the public CI
    log, and it writes a file that is not committed."""
    from datetime import UTC, date, datetime, timedelta

    from job_match.ai.report import build_report, format_report
    from job_match.config.loader import load_settings
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import AiRepository

    today = datetime.now(UTC).date()
    since = today - timedelta(days=7)
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            sys.exit(1)
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    settings = load_settings(_config_dir() / "settings.yaml")
    with Database(path=str(db_path)) as db:
        repo = AiRepository(db.conn)
        report = build_report(repo.list_disagreements(since), repo.usage_since(since),
                              settings, since, today, runs=repo.list_runs(since))
    out = Path(args.out) if args.out else _data_dir() / f"ai-report-{today.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_report(report), encoding="utf-8")
    print(
        f"AI report: {report.total} disagreements since {since.isoformat()}"
        f" ({report.with_decision} with a Tri verdict) -> {out}"
    )


def _cmd_funding_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.config.loader import load_settings
    from job_match.funding.article import ArticleFetcher
    from job_match.persistence.db import Database
    from job_match.pipelines.funding import run_funding

    cfg = _config_dir()
    data_dir = _data_dir()
    settings = load_settings(cfg / "settings.yaml")
    sources = _build_funding_sources(settings.funding.sources)
    fetcher = ArticleFetcher(requests_per_second=settings.funding.requests_per_second)

    if args.dry_run:
        db_path = ":memory:"
        print("[DRY RUN] in-memory DB: every article counts as new, nothing is written")
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(data_dir / "jobs.sqlite")

    started = time.perf_counter()
    try:
        with Database(path=db_path) as db:
            summary = run_funding(
                sources, settings, db, fetcher, limit=args.limit, dry_run=args.dry_run,
            )
    except Exception as exc:
        _fail_loudly("Funding run", exc)
        raise

    _print_funding_summary(summary, dry_run=args.dry_run)
    append_step_summary(funding_markdown(summary, time.perf_counter() - started))


def _cmd_funding_reprocess(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import date

    from job_match.config.loader import load_settings
    from job_match.funding.article import ArticleFetcher
    from job_match.persistence.db import Database
    from job_match.pipelines.funding import reprocess_funding

    since: date | None = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"Invalid date {args.since!r} — expected YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    cfg = _config_dir()
    settings = load_settings(cfg / "settings.yaml")
    fetcher = ArticleFetcher(requests_per_second=settings.funding.requests_per_second)
    db_path = str(_data_dir() / "jobs.sqlite")  # reprocess always reads the real DB

    if args.dry_run:
        print("[DRY RUN] extraction runs on stored articles, nothing is written")

    with Database(path=db_path) as db:
        summary = reprocess_funding(
            settings, db, fetcher, since=since, limit=args.limit, dry_run=args.dry_run,
        )

    _print_funding_summary(summary, dry_run=args.dry_run, kind="reprocess")


def _print_funding_summary(
    summary: RunSummary, *, dry_run: bool = False, kind: str = "run"
) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nFunding {kind} complete{tag}")
    if kind == "run":
        print(f"  feeds:      {summary.feeds}")
        print(f"  found:      {summary.fetched}")
        print(f"  new:        {summary.articles}")
        print(f"  skipped:    {summary.duplicates}  (already seen)")
    else:
        print(f"  selected:   {summary.fetched}")
        print(f"  processed:  {summary.articles}")
    print(f"  errors:     {summary.errors}")
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    print(f"  funding:    {summary.funding_articles}  "
          f"(articles, no company: {summary.funding_no_company})")
    print(f"  events:     {summary.funding_events}")
    print(f"  leads:      {summary.leads}  (deduped: {summary.leads_deduped})")
    if summary.by_source:
        print("  by source:")
        for name in sorted(summary.by_source):
            b = summary.by_source[name]
            print(f"    {name:<12} articles={b.get('articles', 0)} funding={b.get('funding', 0)} "
                  f"events={b.get('events', 0)} leads={b.get('leads', 0)}")


def _print_top_departments(by_department: dict[str, int], top: int = 10) -> None:
    """Where the offers are, biggest first. "?" = no single department (region or unknown)."""
    ranked = sorted(by_department.items(), key=lambda kv: (-kv[1], kv[0]))
    print(f"  fetched per department, from the offer location (top {top}):")
    for dept, count in ranked[:top]:
        print(f"    {dept}: {count}")
    if len(ranked) > top:
        rest = sum(count for _dept, count in ranked[top:])
        print(f"    +{len(ranked) - top} more departments: {rest}")


def _print_summary(summary: RunSummary, *, dry_run: bool = False) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nJobs run complete{tag}")
    print(f"  queries:    {summary.queries}  (keyword x area)")
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
    print(f"  stretch:    {summary.stretch}  (experience within stretch_years; never strong)")
    if summary.rqth_recruiter:
        print(
            f"  RQTH recruiter offers: {summary.rqth_recruiter}"
            f" (end client named: {summary.rqth_end_client})"
        )
    if summary.pipeline == "jobs":
        print(f"  checked:    {summary.checked}  (stored offers re-checked at the source)")
        print(f"  closed:     {summary.closed}  (hidden from the digest and the dashboard)")
        print(f"  raw payloads: stored {summary.raw_stored} (new or changed),"
              f" pruned {summary.raw_pruned}")
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
    if summary.by_source:
        print("  per source (fetched / eligible / duplicates / api calls):")
        for name in sorted(summary.by_source):
            c = summary.by_source[name]
            print(
                f"    {name:<16} {c.get('fetched', 0):>5} / {c.get('eligible', 0):>4}"
                f" / {c.get('duplicates', 0):>4} / {c.get('calls', 0):>4}"
            )
    if summary.by_area:
        print("  fetched per queried area:")
        for area, count in sorted(summary.by_area.items()):
            print(f"    {area}: {count}")
    if summary.by_department:
        _print_top_departments(summary.by_department)
    if summary.by_keyword:
        # Query keywords come from the private profile and this output lands in a public
        # CI log: departments are printed, the per-keyword breakdown stays at DEBUG.
        _logger.debug(
            "fetched per keyword: %s",
            ", ".join(f"{kw}={count}" for kw, count in sorted(summary.by_keyword.items())),
        )
