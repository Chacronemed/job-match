# ADR 0028: Auto-archive of stale « À candidater » applications

**Status:** accepted, 2026-11-06

## Context

An offer I keep in Tri becomes an « À candidater » application and stays there until I act.
When I do not, it sits in the Kanban's first column, in the table, in the sidebar count and in
« Générer les manquants » for weeks, while the posting itself is three weeks old and the
employer has moved on. Deleting it would lose the decision, the documents and the history;
leaving it costs attention every day. « Expirée » (ADR 0024) already derives a state from a
fact outside D1 (the offer closed) without storing a status.

## Decision

1. **A derived state, « Archivée », for the `to_apply` status only.** An application is
   archived when it was kept more than `archive.kept_days` (15) days ago without becoming
   « Envoyée », or when its offer was published more than `archive.published_days` (20) days
   ago. The kept day is the « Réactiver » date when there is one, else the « Garder »
   decision (the latest decision when it is `good_fit`); an application kept without a
   decision has no kept day, so only the published rule can archive it. Unknown publication
   date: the kept rule alone. « Expirée » wins over « Archivée ». Thresholds in
   `settings.yaml` → `archive`; the page (`tracking.js` `ARCHIVE`) and the Worker
   (`worker/src/archive.js`) repeat them, a Python test keeps the three equal and a Node test
   runs both JavaScript copies on the same table of cases.
2. **Nothing is written by the CI or the Daily run.** The page derives the state at render
   time from `/api/applications` (statuses, latest decisions with their dates, `reactivated_at`)
   and `data.json` (`published_at`, `closed`); the Worker derives it the same way for the
   documents; the Python side derives it from the tracking mirror for the digest's follow-ups
   and the run summary.
3. **« Réactiver »** (record panel and the archived section) is the only write: `POST
   /api/applications/:key/reactivate` sets `reactivated_at = now` (D1 migration 0009, mirrored
   by Python migration 0013 and the Daily run's export). The kept counter restarts from that
   date and the published rule is switched off for that application. 404 without a row, 409
   when the status is not `to_apply`.
4. **Effects.** Out of the Kanban, the table and the sidebar count by default; « Afficher les
   archivées » (`#candidatures?archived=1`) adds a folded section under either view with a
   grey badge, the reason (« gardée il y a 17 jours » / « publiée il y a 23 jours »), the
   existing documents' links and « Réactiver »; no « Postuler », no « Générer », out of the
   due follow-ups. The Worker's cron auto-queue, « Générer les manquants » and the pending
   rows skip it (a pending row fails with `error_code: archived`); the digest lists no
   follow-up for it. The record panel shows « Archivée · <raison> » and « Réactiver » in its
   footer. The run summary and the Exécutions card say « N candidatures archivées
   aujourd'hui » (`RunSummary.archived_today`, with the total).

## Alternatives considered

- A stored D1 status `archived` written by the Daily run: a CHECK rebuild, a write to D1 from
  CI, and a state to undo by hand when the offer or my plans change; the derived state costs
  nothing and reverses itself (a new « Garder » decision restarts it).
- Counting from `updated_at` when there is no decision: every note edit would restart the
  counter, and the stored date says nothing about when I decided to keep the offer.
- Archiving `to_review` offers too: they already age out of the list with
  `jobs.max_age_days`; the problem was the kept ones I never sent.

## Consequences

- An application kept from the status menu (no Tri decision) is archived by the published
  rule only; the stats view already counts it as « gardée sans date ».
- `reactivated_at` reaches the Python mirror only after the D1 migration runs (the Daily
  run applies it before the export); an export taken before it still imports.
- The Statistiques view's own « Archivées » tile (offers tracked but no longer listed) keeps
  its earlier meaning; it is not this state.
