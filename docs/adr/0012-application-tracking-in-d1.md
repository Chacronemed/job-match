# ADR 0012: Application tracking in Cloudflare D1, behind the dashboard's Access

**Status:** accepted (2026-10-20, M21). Amends ADR 0009 (decisions 1 and 4) and ARCHITECTURE §10.

## Context

The dashboard showed offers but could not record what I did with them: applied, ignored, when
to follow up. Three consequences followed. The digest kept mailing jobs I had already handled.
Nothing reminded me to follow up. My verdicts on the scorer's matches were lost.

Three constraints shaped the answer:
- **A static site cannot write anything.**
- **`localStorage` would stay in one browser.** It would be invisible to the daily pipeline, so
  the digest could never use it, and it would be lost with the browser profile.
- **The repo is public.** Notes, CV links and statuses are private.

## Decision

1. **Store my actions in D1** (`job-match-tracking`, free tier). D1 is the source of truth for my
   actions; the jobs SQLite DB stays the source of truth for offers.
   - Tables: `applications`, keyed by `job_key` = `<source>:<source_job_id>` (the natural key,
     never the SQLite surrogate id), and `decisions`, a verdict log.
   - Migrations live in `worker/migrations/`.
2. **The same Worker (`job-match`) gets code, only for `/api/*`** (`assets.run_worker_first`).
   Every other path is still served as static assets.
   - Routes: `GET /api/applications`, `PUT /api/applications/:key`, `POST /api/decisions`.
3. **Access stays the only way in, and the Worker re-checks it on every API call.**
   - It verifies the `Cf-Access-Jwt-Assertion` JWT: RS256, the team's JWKS cached for an hour,
     the `aud` and `iss` claims, and expiry.
   - It refuses a cross-origin request, JSON only, no CORS.
   - It validates every field. Errors never echo input.
   - `CF_ACCESS_AUD` and `CF_ACCESS_TEAM_DOMAIN` are Worker secrets. If either is missing, the
     Worker answers 500 and refuses to serve.
4. **The page fetches `/api/` on the same origin** (CSP `connect-src 'self'`).
   - Saves are optimistic and revert to the stored values on failure.
   - Notes and links only reach the DOM as text or as a checked `https:` href.
   - Opened from a file, or with the API down, the page works as before and shows a banner.
5. **The daily run mirrors D1 into the jobs DB before the digest**, as a read-only copy.
   - `wrangler d1 execute --json` writes to a temp file. `job-match tracking import` then
     validates every row and replaces the mirror in one transaction.
   - The digest leaves out jobs whose status is not `to_review`/`to_apply`, and lists due
     follow-ups first ("Relances du jour"). Follow-ups are never marked as notified.
   - A failed export keeps the previous mirror, which travels in the DB snapshot.
   - The log shows counts only.

## Alternatives

- **localStorage:** invisible to the pipeline and to other devices.
- **Commit statuses to the private data repo from the page:** needs a GitHub token in the
  browser.
- **Workers KV:** no SQL, and an export that is harder to validate.
- **A separate API Worker:** a second hostname, a second Access application, and CORS.
- **career-ops' tracker:** a manual tool on a single machine, out of reach of the pipeline.
  career-ops stays the tool for evaluation and CV tailoring. This only records statuses.

## Consequences

- The dashboard is no longer pure static. There is server code to secure, and it is tested
  (`worker/test/`, Node's built-in runner, run from pytest and in CI).
- The API token needs **D1 Edit** in addition to **Workers Scripts Edit**.
- The digest reflects statuses as of the morning export. A change made after 07:00 UTC counts
  the next day.
- Statuses are not in `data.json`. The page reads them live, so the snapshot never carries notes.
