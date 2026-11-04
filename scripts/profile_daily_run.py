"""Profile one daily run on a synthetic snapshot.

    .venv\\Scripts\\python scripts/profile_daily_run.py [stored=3000] [new=400]

Builds a throw-away SQLite (`data/profile.sqlite`, gitignored) with `stored` synthetic French
postings over 30 days in ten runs, then pushes one day of `new` postings plus reposts through
`run_jobs` under cProfile with a SQL statement counter, and times the digest and dashboard
queries with their EXPLAIN QUERY PLAN. Prints aggregates only. The numbers of the 2026-11-04
pass are in docs/adr/0022-stored-dedup-blocks.md.
"""
import cProfile
import io
import pstats
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_match.config.loader import (  # noqa: E402
    load_aliases,
    load_profile,
    load_settings,
    load_skill_vocabulary,
)
from job_match.dashboard.data import build_dashboard_data  # noqa: E402
from job_match.domain.models import Job, WorkplaceType  # noqa: E402
from job_match.normalization.contract import parse_contract_type  # noqa: E402
from job_match.persistence.db import Database  # noqa: E402
from job_match.persistence.repositories import JobRepository  # noqa: E402
from job_match.pipelines.jobs import run_jobs  # noqa: E402

TITLES = ["Ingénieur DevOps", "Site Reliability Engineer", "Ingénieur Cloud AWS",
          "Platform Engineer", "Ingénieur Infrastructure Kubernetes", "SRE Senior",
          "DevOps Junior", "Administrateur Système Linux", "Architecte Cloud",
          "Release Engineer", "Développeur PHP", "Réceptionniste d'hôtel",
          "Ingénieur DevOps (H/F)", "Lead DevOps confirmé", "Consultant SAP",
          "Technicien support N1"]
COMPANIES = ["Orbital Systems", "Nuage SAS", "Kappa Cloud", "Hexalabs", "Ferrovia Tech",
             "Lumen Data", "Atelier Numérique", "Boréal", "Cime Logiciels", "Delta Ops", "",
             "ACME SARL", "Acme", "Datalys Group"]
PLACES = ["75 - Paris", "69 - Lyon", "33 - Bordeaux", "31 - Toulouse", "44 - Nantes",
          "59 - Lille", "92 - Nanterre", "13 - Marseille", "Île-de-France", "New York, NY",
          "Berlin", "75056 - Paris", "Télétravail", "Bretagne", "06 - Nice"]
SKILLS = ["Kubernetes", "Terraform", "AWS", "Docker", "Ansible", "Python", "GitLab CI",
          "Prometheus", "Linux", "Azure", "GCP", "Helm", "ArgoCD", "k8s", "CI/CD", "Grafana",
          "Bash", "Windows Server", "PHP", "SAP", "COBOL", "Jenkins", "Go"]
EXP = ["", "Vous justifiez de 3 ans d'expérience minimum sur des plateformes cloud.",
       "Première expérience appréciée.", "Minimum 5 ans d'expérience en production.",
       "2 à 4 ans d'expérience.", "Expérience solide sur Kubernetes.",
       "Débutant accepté, formation assurée.", "Au moins 7 ans d'expérience en architecture.",
       "Un an d'expérience suffit.", "Profil senior : 8+ ans."]
CONTRACTS = ["CDI", "CDI", "CDI", "CDD", "Freelance", "Stage", "Alternance", ""]
PARAS = ["Nous recherchons un ingénieur pour rejoindre notre équipe plateforme.",
         "Vous participerez à la mise en place de l'infrastructure.",
         "Astreintes possibles, télétravail partiel.",
         "Poste basé au siège, déplacements occasionnels.",
         "Vous serez garant de la disponibilité des services.",
         "Environnement agile, équipe de 12 personnes."]
NOW = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


def make_items(n: int, seed: int, start: datetime, days: int = 30,
               dup_rate: float = 0.15) -> list[dict]:
    """Deterministic postings; `dup_rate` of them are reposts of an earlier one."""
    rng = random.Random(seed)
    items: list[dict] = []
    for i in range(n):
        if items and rng.random() < dup_rate:
            base = rng.choice(items)
            item = dict(base, id=f"{seed}-{i}",
                        description=base["description"] + " Rejoignez-nous !")
            if not base["title"].endswith("(H/F)"):
                item["title"] = base["title"] + " (H/F)"
            items.append(item)
            continue
        skills = rng.sample(SKILLS, rng.randint(1, 6))
        contract = rng.choice(CONTRACTS)
        text = [rng.choice(PARAS), "Compétences : " + ", ".join(skills) + ".",
                rng.choice(EXP), rng.choice(PARAS), f"Contrat : {contract}." if contract else ""]
        items.append({
            "id": f"{seed}-{i}", "title": rng.choice(TITLES), "company": rng.choice(COMPANIES),
            "location": rng.choice(PLACES), "contract": contract,
            "description": "\n".join(t for t in text if t),
            "published_at": (start - timedelta(days=rng.randint(0, days))).isoformat(),
            "url": f"https://example.test/{seed}/{i}",
        })
    return items


class Source:
    name = "france_travail"

    def __init__(self, items: list[dict], at: datetime) -> None:
        self._items, self._at = items, at

    def fetch(self, since=None):
        yield from self._items

    def to_job(self, raw: dict) -> Job:
        return Job(
            source=self.name, source_job_id=raw["id"], title=raw["title"],
            company=raw["company"], location=raw["location"],
            workplace_type=WorkplaceType.UNKNOWN,
            contract_type=parse_contract_type(raw["contract"], raw["title"], raw["description"]),
            description=raw["description"], url=raw["url"],
            published_at=datetime.fromisoformat(raw["published_at"]),
            collected_at=self._at, search_query="devops",
        )


def main(stored_n: int, new_n: int) -> None:
    cfg = Path("config")
    profile = load_profile(cfg / "profile.example.yaml")
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    vocab = load_skill_vocabulary(cfg / "skill_vocabulary.yaml")
    db_path = Path("data") / "profile.sqlite"
    db_path.parent.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)

    with Database(path=str(db_path)) as db:
        hist = make_items(stored_n, seed=1, start=NOW - timedelta(days=1), days=30)
        chunk = len(hist) // 10 + 1
        for k in range(10):
            at = NOW - timedelta(days=30 - 3 * k)
            run_jobs(Source(hist[k * chunk:(k + 1) * chunk], at), profile, settings, db,
                     aliases, vocabulary=vocab)
        today = make_items(new_n, seed=2, start=NOW, days=3)
        rng = random.Random(3)
        for i, base in enumerate(rng.sample(hist, new_n // 6)):  # reposts across runs
            today.append(dict(base, id=f"repost-{i}", title=base["title"] + " (H/F)"))

        sql = {"n": 0}
        db.conn.set_trace_callback(lambda stmt: sql.__setitem__("n", sql["n"] + 1))
        pr = cProfile.Profile()
        t0 = time.perf_counter()
        pr.enable()
        summary = run_jobs(Source(today, NOW), profile, settings, db, aliases, vocabulary=vocab)
        pr.disable()
        wall = time.perf_counter() - t0
        db.conn.set_trace_callback(None)
        print(f"run: {len(today)} new on {stored_n} stored: {wall:.2f} s, {sql['n']} SQL "
              f"statements; rejected={summary.rejected_jobs} dup={summary.duplicates} "
              f"eligible={summary.eligible} strong={summary.strong}")
        out = io.StringIO()
        pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats("job_match", 12)
        print("\n".join(line for line in out.getvalue().splitlines() if "job_match" in line))

        repo = JobRepository(db.conn)
        timed = (
            ("digest list_unnotified", lambda: repo.list_unnotified(
                settings.strong_threshold, now=NOW, max_age_days=45)),
            ("dashboard list_canonical_scored", lambda: repo.list_canonical_scored(
                now=NOW, max_age_days=45)),
            ("build_dashboard_data", lambda: build_dashboard_data(db, settings, NOW)),
        )
        for label, fn in timed:
            sql["n"] = 0
            db.conn.set_trace_callback(lambda stmt: sql.__setitem__("n", sql["n"] + 1))
            t0 = time.perf_counter()
            fn()
            print(f"{label}: {(time.perf_counter() - t0) * 1000:.1f} ms, {sql['n']} statements")
            db.conn.set_trace_callback(None)
        for label, query in (
            ("digest", "SELECT j.* FROM jobs j LEFT JOIN job_duplicates d"
                       " ON d.duplicate_job_id = j.id WHERE j.eligibility IN ('ELIGIBLE','STRETCH')"
                       " AND j.notified_at IS NULL AND d.duplicate_job_id IS NULL"
                       " ORDER BY j.score DESC, j.collected_at DESC"),
            ("dedup title block", "SELECT id FROM jobs WHERE collected_at >= '2026-10-01'"
                                  " AND title_normalized = 'x' AND location_dept = '75'"),
        ):
            rows = db.conn.execute("EXPLAIN QUERY PLAN " + query).fetchall()
            print(f"plan {label}: " + " | ".join(r[3] for r in rows))


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:3]]
    main(args[0] if args else 3000, args[1] if len(args) > 1 else 400)
