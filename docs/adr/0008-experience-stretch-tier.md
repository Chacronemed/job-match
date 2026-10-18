# ADR 0008 — Experience stretch tier

**Status:** accepted (2026-10-18)

## Context

Experience is a hard gate (CLAUDE.md rule 3): required years above the candidate's means
rejected, never a score penalty. Measured on the local DB before any change (533 jobs, candidate
with 2 years, digest threshold 60), 145 jobs were rejected **only** for experience, no other gate
failed:

| required years | jobs | would score ≥ 60 | would be strong (≥ 70) |
|---|---|---|---|
| exactly 3 | 25 | 21 | 13 |
| 4 | 8 | 8 | 7 |
| 5 or more | 68 | 39 | 22 |
| seniority keyword only ("confirmé", "senior", "expert") | 44 | 29 | 11 |

One year over is a conversation, not an impossibility: 21 jobs the digest never showed, 13 of
them strong by skills, a 25% lift on the 85 eligible jobs of the same DB. Five years over is not.

## Decision

1. **A stretch band, configured in `settings.yaml`** (`experience.stretch_years`, 1). A job is
   **STRETCH** when `candidate < required <= candidate + stretch_years`, where `required` is the
   explicit number the parser found, else the minimum a seniority keyword implies
   (`seniority_min_years`: "confirmé" is 3). Above the band the gate rejects exactly as before.
   `stretch_years: 0` disables the tier. The hard gate still holds: the band is a declared,
   measured tolerance, not a penalty curve, and nothing in it invents a number.

2. **Stretch is a tier of eligible, not a rejection.** `Eligibility.STRETCH` is a third value of
   the same column. The job passes every other gate (relevance, contract, location) or it is
   rejected for that reason; it is deduplicated and scored exactly like an eligible job, and the
   scoring engine puts the gate's own words first in the explanations:
   `stretch: requires 3y, you have 2`. That line is what the digest shows, so the email and the DB
   never disagree on why a job is in the tier.

3. **Its own digest section, "À tenter (stretch)", after Other Eligible**, sorted by score, same
   `digest.min_score`. A stretch job is never a Strong Match, whatever its score: strong means
   "apply now", stretch means "worth a try". The run summary and `job-match reprocess` count
   `stretch` on its own line, outside `eligible` and `strong`.

Alternatives, one line each: lower `candidate.experience_years` in the profile (lies to every
gate and every digest); a score penalty for the missing year (rule 3 forbids it, and a high skill
score would hide the gap); show stretch jobs mixed into Other Eligible (the reader could not tell
a sure thing from a reach).

## Consequences

- Rows rejected for one year too many become STRETCH on the next `job-match reprocess`; the
  reason is cleared and a score stored. `list_unnotified` and `reset_notified_since` read both
  tiers, so a stretch job is emailed once, in its section.
- `list_eligible` (the "top strong titles" print) and the leads' "open jobs" count stay on
  ELIGIBLE: stretch never inflates a strong count anywhere.
- A seniority keyword alone can put a job in the tier ("DevOps confirmé" with no number). The
  keyword map is config; if "confirmé" turns out to mean 5 somewhere, the map is the fix.
- Widening the band is one number in settings, and the measurement table above says what each
  step would admit: 4 years adds 8 jobs, all above the threshold.
