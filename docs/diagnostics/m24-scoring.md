# M24 diagnostic: a score that told nothing apart

- **Date:** 2026-10-22.
- **Data:** a copy of the production database (7 428 offers collected from 3 to 22 October 2026) and the Tri verdicts mirrored from D1.
- **Tools:** `scripts/diagnose_scoring.py` (aggregates only) and `job-match calibrate`.
- **Privacy:** no company, URL, note or job key appears here. Job titles are public offer data.

## Before (production scoring, 22 October)

| | Offers | Median | Q1 / Q3 | IQR |
|---|---|---|---|---|
| Eligible | 586 scored | 54 | 50 / 63 | 13 |
| Stretch | 302 scored | 57 | 50 / 66 | 16 |

**284 of the 586 eligible offers scored 50 to 54.** 50 is `base_score` with no skill matched.

The most frequent titles among the kept offers (eligible + stretch):

| Count | Mean score | Normalised title |
|---|---|---|
| 20 | 50.0 | responsable d exploitation |
| 13 | 50.0 | agent d exploitation |
| 11 | 78.7 | ingenieur devops |
| 11 | 51.3 | technicien d exploitation |
| 10 | 74.7 | devops |
| 8 | 57.2 | data engineer |
| 8 | 70.0 | ingenieur devsecops |
| 8 | 50.0 | responsable de secteur d exploitation |
| 8 | 50.0 | responsable exploitation |
| 7 | 52.0 | ingenieur banc de test d integration optronique en defense |
| 6 | 55.5 | data manager |
| 6 | 72.0 | ingenieur de production |
| 5 | 50.0 | architecte systeme |
| 5 | 82.4 | ingenieur devops cloud |
| 3 | 50.0 | responsable d exploitation de site hotelier et touristique |
| 3 | 53.0 | product owner |
| 3 | 54.3 | ingenieur en systemes embarques et logiciels temps reel |

The full top 30 comes from the script. Two findings:

1. **The relevance gate let non-IT titles through.** `relevance.target_title_keywords` matches as a word *prefix*. `exploitation`, `administrateur` and `système` therefore let logistics, hospitality and water-plant jobs in ("responsable d'exploitation"). They then scored exactly 50, because no skill matched.
2. **A single skill in the description was enough** (`gate.is_relevant`). A recruiter post, a defence test-bench job or a hardware role that mentions Docker or Linux passed and scored like a DevOps job.

**Share outside the domain.** Classified with the M24 title families (`config/settings.yaml` `title_relevance`), the 888 kept offers split as:
- 40 % other, i.e. no family word in the title;
- 36 % core;
- 16 % near;
- 8 % off-domain.

Across the whole table, 762 of 7 428 titles are off-domain.

**Verdicts.** 7 decisions (6 good_fit, 1 off_topic) and 26 tracked offers (19 dropped without a reason).
- `calibrate`: too few decisions for suggestions (7 < 10); « forte » ≥ 70 was 2/2 good_fit.
- Mean score: kept offers 65.2, dropped offers 56.1, a 9-point gap only.

## Fix (M24)

- **Title families** (`scoring/title.py`, `title_relevance`):
  - **core**: DevOps, SRE, cloud, platform, infrastructure, ops, Kubernetes, AWS/Azure/GCP, Terraform. +20; a core term protects the title.
  - **core_overrides**: a core title that also names a sales, product, project or recruitment role (commercial, sales, ingénieur d'affaires, business developer, product owner, chef de projet, account manager, recruteur) is **other**, −15, and never vetoed. Matched as whole words, so "Salesforce" is not "sales".
  - **off_domain** (trades): recruitment, sales, mechanics, hardware, electronics, embedded, data manager / analyst, product owner, construction sites, HR… Vetoed at the gate with reason `TITLE`, even when a near term is there too.
  - **off_domain_sectors**: transport, marketing, logistique, bâtiment, BTP, hôtel / tourisme, restauration. Vetoed only when no core or near term is in the title. They lose to near on purpose: « restauration » is also a backup restore, « transport » also Axway Secure Transport.
  - **near**: systems / network admin, IT operations, IT production engineering, SysOps, middleware / inter-applicatif, backup, security, data engineer. +10, the level of the old title bonus.
  - **other**: −15. A penalty, not a veto, so recall stays wide.
  - The families replace the legacy `title_bonus`, which was +10 on a profile keyword.
- **Profile section** (`normalization/sections.py`): a preferred skill the offer asks for under « Profil », « Compétences »… counts ×1.5, rounded half up. 489 of the 918 kept offers name such a section.
- **Thresholds:** `strong_threshold` 70 → **80**; `digest.min_score` 60 → **55**.
- **Tri:** the queue now starts at `digest.min_score`. A scored offer below it stays visible in Offres.

## Check of the excluded titles (before the commit)

- **40 random `TITLE` exclusions:** all right (embedded, electronics, sales and pre-sales, product owner / manager, data analyst / manager, accounting, logistics, hospitality, production lines).
- **The 52 exclusions whose description cites at least 3 profile skills:** almost all are data analyst / manager, embedded, developer or product roles.
- **Two false negatives,** both fixed by the sector tier and two near terms:
  - « Spécialiste échanges inter-applicatifs (Secure Transport) », excluded by « transport »;
  - « Data Engineer … customer data / marketing », excluded by « marketing ».

## After (same data, rescored with `job-match reprocess`)

| | Offers | Median | Q1 / Q3 | IQR |
|---|---|---|---|---|
| Eligible | 554 | 60 | 37 / 75 | **38** |
| Stretch | 291 | 62 | 38 / 79 | **41** |

- **The scores now spread out.** Off-trade titles sit at about 35 (base − 15, no skills), DevOps titles at 80–100 (ingénieur devops 92.1, devops 90.1, ingénieur devops cloud 93.4).
- **The titles from the complaint** (consultant en recrutement, mécanique des fluides, hardware, data manager, optronique test bench, hospitality site) are vetoed. 756 offers are rejected for `TITLE`.

| Threshold | Kept offers above | Title families above | My kept offers above | My dropped offers above |
|---|---|---|---|---|
| before ≥ 60 (old digest) | 340 | core 81 %, near 9 %, other 9 %, off 1 % | 5 / 7 | 4 / 18 |
| before ≥ 70 (old strong) | 138 | core 93 % | 3 / 7 | 0 / 18 |
| **after ≥ 55 (new digest)** | **477** | core 67 %, near 30 %, other 3 %, off 0 % | **7 / 7** | 6 / 13 |
| **after ≥ 80 (new strong)** | **157** (19 % of kept) | core 93 % | 3 / 7 | 0 / 13 |

**The Tri as you see it** (open offers, not yet triaged):

| | Offers to sort | core | near | other | off-domain |
|---|---|---|---|---|---|
| Before, no score filter | 624 | 221 | 104 | 251 | 48 |
| **After, from the digest threshold** | **330 (−47 %)** | 221 | 100 | 9 | 0 |

- **Kept vs dropped:** kept offers average 68.8 against 49.3 for the dropped ones, a 19-point gap instead of 9. The off_topic verdict is now rejected at the gate.
- **Email digest:** it counts the non-stretch eligible offers. They go from 209 (≥ 60 before) to about 300 (≥ 55 after) over the window, because the DevOps titles gain +20.
  - The digest is mostly relevant offers now, but there are more of them.
  - `digest.min_score: 60` is the knob if the email feels too long; it loses one kept offer (57).

## To redo after more verdicts

`job-match calibrate` needs 10 decisions to suggest anything. With about 30 more verdicts, rerun this diagnostic and `calibrate` on a fresh copy. Then check the « other » family (43 % of kept offers, mostly below the digest) for real DevOps titles that the lists miss.
