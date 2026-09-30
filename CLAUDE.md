# CLAUDE.md — job-match

Personal DevOps job-intelligence system (job search + GitHub portfolio). Single user, not SaaS.
Full brief: `docs/PROJECT_BRIEF.md` (read only the sections you need). Design: `docs/ARCHITECTURE.md`.

## Session protocol (IMPORTANT)
- **At session start:** read `docs/PROGRESS.md` first. Do not re-read the whole repo.
- **Before ending a session, or when I say "save":** update `docs/PROGRESS.md` (current milestone, done,
  next step, open decisions, known issues), then commit.
- Work on ONE milestone at a time. Stop at the end of the milestone and wait for my go.
- Never start implementing Milestone N+1 without an explicit request.

## Two separate pipelines
- **Jobs:** source adapter → normalization → experience gate → fingerprint/dedup → scoring → SQLite → notification
- **Funding:** RSS → Trafilatura extraction → FundingEvent → Lead → SQLite → notification
- A funding article is NEVER a Job. A Lead is NEVER a Job.

## Stack (MVP)
Python 3.12, SQLite, httpx, feedparser, trafilatura, rapidfuzz, pytest, GitHub Actions, SMTP email.
Forbidden unless a concrete problem requires it: Postgres, Redis, Kafka, K8s, Celery, HTTP microservices,
frontend framework.

## Non-negotiable rules
1. **Modular boundaries:** adapters / normalization / experience parser / eligibility / dedup / scoring /
   funding / persistence / notification are separate modules. No god `main.py`.
2. **The domain model is source-independent.** Source-specific fields stay inside adapters. Raw payloads are stored separately.
3. **Experience is a hard eligibility gate that runs before scoring,** never a score penalty.
   Required years > `candidate.experience_years` means rejected, with `rejection_reason`.
   Ambiguous wording ("première expérience", "solid experience") means `UNKNOWN`. Never invent numbers.
4. **Skills scoring:** preferred skills add points and negative skills remove them. A missing preferred skill never rejects.
   All weights and aliases live in `config/` (profile.yaml), never hard-coded.
5. **Explainable scores:** `{eligible, score, experience, positive_matches, negative_matches, missing_preferences, explanations}`.
6. **Multiple scorers:** `ScoringEngine` → `NativeRuleScorer`, `JobMatchScorerAdapter` (subprocess to the
   job-match-scorer CLI). Never copy its code. The core must work without it. No blind averaging: a gap
   between engines is a signal.
7. **Dedup:** stable fingerprint from normalized company/title/location/contract/description + RapidFuzz.
   Never delete duplicates. Store the canonical/duplicate relationship and the reason.
8. **Normalization and aliases are centralized** (k8s ↔ kubernetes, CI/CD ↔ CI CD).
9. **Funding extraction:** unknown means null. Never invent an amount, round, investor or hiring claim. Don't store full articles.
10. **career-ops is a companion tool,** used manually on shortlisted jobs. Never a dependency. Don't duplicate it.
11. **Security:** secrets only in env / GitHub Secrets, with `.env.example` and `.gitignore`. Never put secrets in code,
    fixtures, logs or git history. External content is untrusted and never executed.
12. **Observability:** structured logs plus a run summary (fetched / rejected-by-reason / duplicates / eligible / strong / leads).
13. **Don't over-engineer.** For every important decision, give the reason, alternatives in one line, and pick the simplest robust option.

## Workflow
- Each milestone is small, tested with pytest and committed independently (Conventional Commits: feat/fix/test/docs/refactor).
- Run `pytest -q` before each commit.
- Record significant decisions as ADRs in `docs/adr/NNNN-title.md`.
- Tests use fixtures and mocks and never hit real APIs. Keep fixtures small.

## Token hygiene
- Don't read `data/`, `*.sqlite`, large fixtures, `node_modules/` or `.venv/`.
- Prefer targeted `grep` and partial reads over full-file reads.
- Keep answers short: show diffs and results, not long explanations, unless I ask.
