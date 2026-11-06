# ADR 0026: the Statistiques view, computed in the page from real data only

**Status:** accepted, 2026-11-06

## Context

I want to see the funnel of my search (vues → gardées → envoyées → réponses → entretiens →
refus), where it leaks, and why I drop offers. All of this already lives in the snapshot
(`jobs`, `tracked`) and in the tracking the page loads (`applications`, latest `decisions`
with `created_at`, `inbox`). There is no event history: an application holds its current
status and a few dates.

## Decision

1. **Computed in the page** (`stats.js`, `window.JMStats.compute`, pure). No new table, no
   Worker change, no library: bars in CSS, the weekly chart in SVG built with
   `createElementNS`. CSP unchanged (one more hashed inline script).
2. **The period is a cohort.** 30 / 90 days = offers collected since `generated_at` minus N
   days, followed to their current status. « Tout » adds the applications whose offer left the
   snapshot. Cohort rates are always ≤ 100 % and every stage counts the same offers.
3. **Dates, never guessed.** gardée = latest verdict « Bon match » (`decisions.created_at`);
   envoyée = `applied_at`; réponse = first linked recruiter reply (`inbox`, applied or
   corrected, acknowledgments excluded). Entretien / refusée without a linked reply still
   count as a réponse, but stay out of the weekly chart and of the delays, and the page says
   how many are undated. A delay is a mean over the pairs that have both dates, with its n.
4. **Expirées** = `T.isExpired` (à candidater, offer closed); **archivées** = tracked offers
   the list no longer shows (closed after applying, or older than `max_age_days`). Both stay
   in the funnel and are also counted on their own.
5. **Compétences manquantes** = the offer's skills not in my profile (`why.unlisted`) over the
   kept offers, minus the ones I marked « je maîtrise ».

## Alternatives

- An event log in D1 (status changes with timestamps): exact weekly flows, but a migration,
  Worker writes and no history for the past. Not needed yet.
- Per-stage windows (each stage counted on its own date): rates can exceed 100 %.

## Consequences

The inbox history is the latest 100 handled replies, so a very old first reply can be
missing (its delay is then not counted). The weekly chart shows at most 26 weeks.
