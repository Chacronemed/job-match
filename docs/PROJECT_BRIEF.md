# PROJECT BRIEF — PERSONAL DEVOPS JOB INTELLIGENCE SYSTEM

> Full reference document. The condensed, always-loaded rules live in `/CLAUDE.md`.
> Read this file only when working on a milestone that needs the detail.

You are my senior software architect, developer, reviewer and technical assistant.

We are building a PERSONAL job-intelligence project for:
1. my own job search;
2. my GitHub portfolio;
3. demonstrating strong software engineering, data, automation and DevOps practices.

This is NOT a commercial product at this stage. Do not optimize for SaaS economics, billing,
multi-tenancy or commercial licensing constraints. The architecture must still remain clean
enough to evolve later.

---

## 0. Architecture overview

There are **two independent pipelines** that share persistence and notification.
A funding article never enters the job pipeline, and a job never enters the funding pipeline.

```
                         ┌─────────────────────┐
                         │      Scheduler      │
                         │   GitHub Actions    │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Python Orchestrator │
                         └──────────┬──────────┘
                                    │
             ┌──────────────────────┴───────────────────────┐
             │                                              │
   ══════ JOB PIPELINE ══════                  ══════ FUNDING PIPELINE ══════
             │                                              │
   ┌─────────┴──────────┐                       ┌───────────┴───────────┐
   ▼                    ▼                       ▼                       ▼
France Travail     Future sources          Maddyness RSS          FrenchWeb RSS
  Adapter          (Adzuna, ...)             Adapter              (future) ...
   └─────────┬──────────┘                       └───────────┬───────────┘
             ▼                                              ▼
      Job Normalization                            Article Extraction
             │                                       (Trafilatura)
             ▼                                              │
      Experience Filter                                     ▼
      (hard eligibility gate)                     Funding Extraction
             │                                     → FundingEvent
             ▼                                              │
      Fingerprint / Dedup                                   ▼
             │                                       Lead Processing
             ▼                                        → Lead
     ┌───────────────┐                                      │
     │ Scoring Layer │                                      │
     └───────┬───────┘                                      │
      ┌──────┴────────┐                                     │
      ▼               ▼                                     │
 Rule-based     job-match-scorer                            │
   scorer      (external CLI, optional)                     │
      └──────┬────────┘                                     │
             ▼                                              │
      Final Job Record                                      │
             │                                              │
             └──────────────────────┬───────────────────────┘
                                    ▼
                                 SQLite
                     (jobs, companies, funding_events, leads)
                                    │
                                    ▼
                           Notification Service
                         ┌──────────┴──────────┐
                         ▼                     ▼
                       Email             Web App (later)
```

Companion tool, outside the system (manual use only):

```
        This system
            │
     shortlisted jobs
            │
            ▼
        career-ops
            │
  deep evaluation / tailored CV /
     interview preparation
```

---

## 1. Product vision

The system answers:

> "Which job opportunities and recruiting signals are relevant to my DevOps profile?"

It is not a generic job board.

Job pipeline:
`SOURCE COLLECTION → NORMALIZATION → HARD FILTERING → DEDUPLICATION → SCORING → STORAGE → NOTIFICATION`

Funding pipeline:
`RSS → article discovery → content extraction → structured extraction → company → FundingEvent → Lead`

**A funding article is NOT a job.**

---

## 2. MVP scope

I am the only user.

Start with: Python, SQLite, France Travail API, RSS feeds, email notification, GitHub Actions, pytest.

Candidate libraries: `requests` or `httpx`, `feedparser`, `trafilatura`, `rapidfuzz`.

Do NOT introduce PostgreSQL, Redis, Kafka, Kubernetes, Celery, message brokers, HTTP microservices
or a frontend framework unless a concrete problem requires them.

The goal is to demonstrate good engineering decisions, not a long list of technologies.

---

## 3. Architectural principle: modular boundaries

The MVP may run in one Python process, but it should behave like independent components:

1. source adapters
2. normalization
3. experience parser
4. eligibility engine
5. fingerprint/dedup engine
6. scoring engine
7. funding/article engine
8. persistence
9. notification

Keep responsibilities separate. No monolithic `main.py`.

---

## 4. Open-source components

Before implementing generic functionality, check whether a mature open-source project can be reused.

### A. job-match-scorer — optional external scoring engine

- Repo: https://github.com/prism-nexus/job-match-scorer (Node, MIT)
- A local, explainable resume-vs-job scorer: TF-IDF cosine similarity, keyword demand coverage,
  configurable weighted dimensions and boilerplate removal.
- **Do not copy its source code.** Wrap it behind an adapter:

```
ScoringEngine (interface)
 ├── NativeRuleScorer
 └── JobMatchScorerAdapter  → subprocess → job-match-scorer CLI → structured result → Python
```

- No network microservice for now. It may become a Docker service later if that helps the portfolio.
- The external scorer must never control the core, and the core must work without it.

### B. career-ops — companion tool

- Repo: https://github.com/career-ops-hq/career-ops (MIT)
- An AI-native local job-search system: evaluation, portal scanning, funding discovery,
  CV tailoring, tracking and interview preparation.
- **Do not duplicate it and do not make it a core dependency.**
- This project focuses on DISCOVERY, FILTERING, DEDUPLICATION, JOB INTELLIGENCE,
  FUNDING SIGNALS and the DAILY DIGEST.
- career-ops is used manually afterwards: shortlisted job → deep evaluation → tailored CV → interview prep.
- Integrate it only if a clean integration point appears naturally, for example an export
  of shortlisted jobs in a format career-ops can read.

---

## 5. Job domain model

A normalized model that does not depend on any source format. Minimum fields:

`id, source, source_job_id, title, company, company_id, location, workplace_type, contract_type,
description, url, published_at, collected_at, fingerprint, eligibility, rejection_reason, score,
scoring_breakdown`

- Keep raw source payloads separately for debugging.
- Never couple the domain model to France Travail's JSON structure.

---

## 5b. Candidate profile (configuration)

My profile lives in configuration, e.g. `config/profile.yaml`, never hard-coded:

```yaml
candidate:
  experience_years: 1
  target_roles: [DevOps, Cloud, SRE, Platform]
  locations: [Île-de-France, Remote]
  contract_types: [CDI, CDD]
skills:
  preferred:
    kubernetes: 15
    terraform: 15
    gcp: 10
    docker: 8
    gitlab-ci: 8
  negative:
    powershell: -8
    windows: -8
aliases:
  kubernetes: [k8s, kube]
  ci-cd: ["ci/cd", "ci cd", "cicd"]
```

The values are examples. Adjust them to the real profile.

---

## 6. Experience is a HARD constraint

- Experience is an **eligibility gate that runs before scoring**. It is not a score penalty.
- If a job explicitly requires more years than `candidate.experience_years`, set
  `eligible = false` and record a `rejection_reason`.
- Never convert it into −10 or −20 points.

Patterns to detect (FR and EN): "3 years", "3+ years", "minimum 3 years", "at least three years",
"5 ans d'expérience", "minimum 3 ans", "2 à 4 ans", "2-4 years", written numbers, ranges, minimums,
and maximums where relevant.

**Ambiguous wording → `experience_requirement = UNKNOWN`.** Never invent a number:
"first professional experience", "some experience", "solid experience", "significant experience",
"expérience significative", "première expérience".

Test many linguistic variations.

---

## 7. Skills / technology scoring

- Keep skills separate from experience constraints.
- Categories: `must_have`, `preferred`, `negative`, `neutral`.
- For the MVP, preferred skills raise the score and negative skills lower it.
- A missing preferred technology never rejects a job.
- All weights live in configuration.

---

## 8. Score explainability

Every scored job must explain its score, in a machine-readable structure:

```json
{
  "eligible": true,
  "score": 82,
  "experience": {"required_min": 0, "status": "ELIGIBLE"},
  "positive_matches": [{"skill": "kubernetes", "weight": 15}],
  "negative_matches": [{"skill": "powershell", "weight": -8}],
  "missing_preferences": ["gcp"],
  "explanations": ["..."]
}
```

---

## 9. Multiple scoring engines

`NativeRuleScorer` and `JobMatchScorerAdapter` can run side by side, and their results can be compared.

- Do not blindly average them. Define and document a clear combination strategy.
- The **gap between engines is itself a signal.** For example, a high rubric/keyword score
  with low text similarity may mean the title and tech look right but the actual role is different.

---

## 10. Fingerprinting and deduplication

- A source ID is not enough, because the same job can appear on several sources with different IDs and URLs.
- Build a canonical representation from normalized company, title, location, contract type
  and relevant description content, then compute a stable hash.
- Use RapidFuzz for near-duplicates.
- **Never delete duplicates.** Store relationships (`canonical_job`, `duplicate_source`,
  `duplicate_reason`) so everything stays traceable.

---

## 11. Normalization

- Normalize accents, case, whitespace, punctuation, company names, job titles and URLs.
- Handle aliases (`k8s` ↔ `kubernetes`, `CI/CD` ↔ `CI CD`) in one centralized alias configuration
  used by the matching layer. Do not scatter string replacements across the code.

---

## 12. Funding / news intelligence (separate pipeline)

`RSS → article discovery → content extraction → structured extraction → FundingEvent → Lead`

FundingEvent fields: company, amount, currency, round, date, investors, sector, location,
recruiting signal, source, article URL, collected timestamp.

**A Lead is NOT a Job.** "Startup raises €10M and plans to hire" produces a FundingEvent and a Lead,
never a Job. Later, Company + FundingEvent + Job can be linked to reveal recruiting patterns.

---

## 13. Article extraction

- Try Trafilatura before writing any custom HTML extraction.
- Do not store full articles. Store source, URL, title, publication date, the structured facts,
  the company and the funding event.
- Unknown values stay null. **Never invent an amount, round, investor or hiring statement.**

---

## 14. Source adapters

```
JobSource.fetch_jobs()          → FranceTravailSource, AdzunaSource, ...
FundingSource.fetch_articles()  → MaddynessSource, FrenchWebSource, ...
```

Nothing outside an adapter may know about source-specific fields.

---

## 15. Database

SQLite for the MVP. Conceptual tables: `jobs`, `companies`, `funding_events`, `leads`, `sources`,
and `job_sources` / duplicate relationships. Use a simple migration strategy and do not
design for a hypothetical SaaS.

---

## 16. Email

```
NotificationService
 ├── EmailNotifier
 └── FutureWebNotifier
```

The digest contains new strong matches, relevant matches, useful rejection statistics,
new funding leads and links to the original sources. Email is not the core domain.

---

## 17. Web app (later)

The domain layer must be consumable by CLI, email, a web API and a web UI.
No frontend during the first MVP iteration.

---

## 18. Automation

The GitHub Actions daily workflow:

1. installs dependencies
2. runs tests
3. runs the collector
4. persists data (the strategy for SQLite across runs must be decided: artifact, cache or a data branch)
5. generates the digest
6. sends the email

API keys and SMTP credentials are GitHub Secrets. Secrets must never appear in code, fixtures,
the README, logs or git history.

---

## 19. Observability

Use structured logging and print a run summary like this:

```
Fetched: 127 | Normalized: 125 | Rejected by experience: 41 | Rejected by hard filters: 23
Duplicates: 18 | Eligible: 43 | Strong matches: 9 | Funding articles: 12 | Leads: 4
```

---

## 20. Test strategy

- **Experience parser:** 3 years, three years, 3+, minimum 3, 2–4, 5+, French variants, ambiguous wording.
- **Normalization:** accents, case, whitespace, aliases.
- **Dedup:** same source, cross-source, slightly modified descriptions, different URLs.
- **Scoring:** positive, negative, missing preferred, eligible vs ineligible, breakdown.
- **API:** pagination, transient errors, rate limiting, malformed responses, timeouts.
- **RSS:** invalid feed, duplicate article, missing metadata.

---

## 21. Security

- Use environment variables, `.env.example` and `.gitignore`.
- Validate and treat all external content (job descriptions, articles) as untrusted.
- Never execute anything that originates from an external source.

---

## 22. Milestones

| # | Milestone |
|---|-----------|
| 0 | Repository audit + architecture |
| 1 | France Travail adapter |
| 2 | Normalized Job domain model |
| 3 | Experience parser + eligibility engine |
| 4 | Native rule-based scoring engine |
| 5 | SQLite persistence |
| 6 | Fingerprint + deduplication |
| 7 | job-match-scorer adapter |
| 8 | Email digest |
| 9 | GitHub Actions automation |
| 10 | RSS article ingestion |
| 11 | Funding extraction |
| 12 | Lead ↔ Company ↔ Job relationships |
| 13 | Optional web application |

Each milestone is small, testable and committed independently.

---

## 23. Portfolio quality

The repository demonstrates clean architecture, meaningful commits, unit tests, configuration management,
error handling, API integration, data processing, deduplication, automation, CI, documentation
and ADRs. Docker is used only when justified.

The README will eventually contain: Problem, Solution, Architecture, Data flow, Screenshots,
Example digest, Configuration, How to run, Testing, Architecture decisions, Roadmap.
It explains *why* each decision was made.

---

## 24. Do not over-engineer

A simple component with good tests beats a distributed system with unnecessary infrastructure.
A Python app that calls an external job-match-scorer process is fine.
An HTTP microservice is not needed at first.

---

## 25. First task (Milestone 0)

Do NOT write implementation code. Inspect the repository, then produce the following
in `docs/ARCHITECTURE.md`:

1. repository audit
2. proposed directory structure
3. Mermaid architecture diagram (two separate pipelines)
4. domain model
5. database schema proposal
6. source adapter interfaces
7. experience eligibility design
8. scoring architecture
9. job-match-scorer integration strategy
10. career-ops companion-tool strategy
11. fingerprint strategy
12. testing strategy
13. milestone roadmap
14. technical risks

For every important decision, explain the reasoning, mention alternatives briefly and prefer
the simplest robust solution. Then **STOP** and wait for "start Milestone 1".
