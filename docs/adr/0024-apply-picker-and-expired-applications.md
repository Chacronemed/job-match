# ADR 0024: `job-match apply` without a key, « Postuler », expired applications

**Status:** accepted, 2026-11-06

## Context

`job-match apply <job_key>` (ADR 0023) asks me for a key I never see and for an ATS I should
not have to know. And a kept offer can close without the application noticing: Devoteam
« Consultant Cloud Ops (H/F) » closed on SmartRecruiters and stayed « À candidater », because
the board lists more than `max_postings` French postings, so an unlisted id was UNKNOWN
forever, and a kept offer past `jobs.max_age_days` was never asked about at all.

## Decision

1. **`job-match apply` with no argument** prints a numbered list and takes a number
   (`src/job_match/apply/picker.py`): applications `to_apply` in D1 (live), offer open in the
   local jobs DB, form supported (`detect_ats`: Greenhouse, Lever, Ashby), oldest
   `updated_at` first, then key. The key stays accepted. An offer missing from the local DB
   is counted and named as a possible numbering gap.
2. **« Postuler »** on each « À candidater » row of the Candidatures table: a supported form
   copies `.venv\Scripts\job-match apply` and the toast names the number, computed by
   `T.applyList` with the CLI's rule (`APPLY_FORMS` = `ATS_HOSTS`, checked by a test); any
   other form opens the offer. Under the title, « Pré-remplissage » / « Manuel ». The data
   carries `apply_form` per offer, computed in Python from the URL.
   *Alternative:* a `jobmatch://` protocol handler launching the CLI: a registry entry and a
   way for a web page to start a local program; rejected.
3. **Closure covers every ATS.** A listing cut at `max_postings` now asks about the one
   unlisted posting: SmartRecruiters' detail call (404 or `active: false` = CLOSED), a Workday
   search on the requisition id over the whole board (an answer without it = CLOSED). A failed
   call stays UNKNOWN. `list_to_check` also takes every job kept `to_apply`, whatever its
   age, eligibility or duplicate link.
4. **« Expirée » is derived, not stored**: `to_apply` + the offer `closed` (now in
   `data.json`). D1 keeps `to_apply`. The page shows a grey badge, sorts the row last, keeps
   it out of the Kanban column, the due list, « Générer les manquants » and « Postuler »; the
   Worker queues no documents for it and fails a pending row with `offer_gone`; the digest
   lists no follow-up for it.
   *Alternative:* a D1 status `expired` written by the Daily run: a table rebuild for the
   CHECK list, a write to D1 from CI, a status to undo if the offer reappears; rejected.

## Consequences

- An offer the source shows again (`mark_open`) un-expires the application by itself.
- The Workday search assumes the requisition id is searchable; on a tenant where it is not,
  a capped board would close a live offer. Watch the run summary's `closed` count for a jump.
- The CLI's numbers can differ from the page's when the local jobs DB is older than the
  site: the list prints title and company before I type.
