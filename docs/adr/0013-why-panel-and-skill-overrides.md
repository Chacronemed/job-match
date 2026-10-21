# ADR 0013: "Pourquoi cette offre ?" panel, skill overrides and decision-based calibration

**Status:** accepted (2026-10-21, M22). Amends ADR 0009 (the dashboard allow-list) and ADR 0012
(the tracking tables and the workflow order).

## Context

The details row showed a score and a list of explanation strings, but not *why*. Three gaps:
- Matched skills were bare names. Their weight survived only inside text such as
  "Matched preferred: kubernetes (+3)", and nothing recorded where in the offer a skill was found.
- An offer's other skills were invisible. A skill the offer asks for that the profile does not
  list was never named, so I could not say "I have that one".
- Experience kept the matched phrase ("au moins 3 ans") but not its sentence. Nothing said
  whether the gate's required years came from a number or from a seniority keyword: the
  dashboard parsed them back out of the stretch note.

The verdict buttons (ADR 0012) stored each verdict with the score at decision time, but
nothing read them back.

## Decision

1. **Evidence is fixed at scoring time, in the breakdown JSON.** No new column or migration:
   `_breakdown_from_json` reads every key with a default, so old rows still load.
   - The scorer records three things:
     - `evidence` (skill → the sentence it was found in, at most 160 characters);
     - `weights` (skill → weight);
     - `unlisted` (vocabulary skill found in the offer but neither preferred nor negative
       → its sentence).
   - `experience_detail` holds `required_years`, `basis`, `sentence` and
     `excludes_apprenticeship`.
     - `basis` is `explicit`, `seniority`, `unknown` or `not_mentioned`, decided by the gate.
     - `sentence` comes from the parser, or is the sentence holding the seniority keyword.
   - Rows scored before M22 show "non recalculé" until the next reprocess.
2. **A committed skill vocabulary** (`config/skill_vocabulary.yaml`, aliases in
   `aliases.yaml`). Unlisted skills never change a score. Everyday words are kept out ("chef",
   "flux", "go"), because matching is whole-term.
3. **The allow-list widens by one sentence per finding.** The dashboard now carries those
   sentences (capped at 240 characters in `data.py`). It still never carries a description.
   The page sits behind Access, and every string is rendered as text.
4. **"je maîtrise" is a D1 table**, `skill_overrides(skill, created_at)`, written through
   `PUT` / `DELETE /api/skill-overrides/:skill`.
   - Auth, origin and error rules are the same as the other routes.
   - A name must be a lowercase term of at most 40 characters.
   - It is mirrored like the other tables. The mirror drops any name not in the vocabulary,
     since the dashboard only offers vocabulary terms.
   - `run` and `reprocess` merge the mirrored overrides into the profile as preferred skills
     with `scoring.override_weight` (2). The relevance gate sees them too. A name the profile
     already lists is ignored.
   - Only the count is logged, never the names.
5. **The D1 mirror moves before the jobs pipeline** in `daily.yml`, so today's run uses
   today's overrides.
   - The import compares the new override set with the old one, and writes
     `overrides_changed` to `$GITHUB_OUTPUT`.
   - When the set changed, "Reprocess for skill overrides" runs `job-match reprocess --since
     <today − jobs.max_age_days> --limit 0`. That re-scores the visible window with no API
     call.
   - The digest still runs after the mirror, so it reads statuses as fresh as before.
6. **`job-match calibrate` reports and suggests; it never applies anything.**
   - It reads the latest verdict per job joined to the stored breakdown, and reports four
     things:
     - the precision of strong;
     - the score distribution per label;
     - the rules most over-represented on off_topic jobs (smoothed lift, support ≥ 3);
     - the unlisted skills named on missing_skill jobs.
   - From 10 verdicts on, it suggests a threshold (best precision while keeping half of the
     good_fit jobs) and weight or profile changes.
   - It is local only: its output names skills, and the CI log is public.

## Alternatives

- **Columns for the experience basis:** a migration buys nothing. Only the scored (visible)
  jobs need it, and they all have a breakdown.
- **Overrides in `localStorage`:** the pipeline could never see them (same reason as ADR 0012).
- **Re-scoring every stored job daily:** pointless work on most days. The conditional
  reprocess runs only after a change.
- **Auto-tuning weights from verdicts:** a few dozen verdicts would overfit. A suggestion that I
  apply by hand keeps the config readable (CLAUDE.md rule 4).

## Consequences

- Production rows get evidence after one manual `reprocess_since` run, or after the first
  override change.
- The vocabulary is a list to maintain: a skill missing from it is never offered.
- Each scored row's breakdown JSON grows by a few hundred bytes of sentences.
