# ADR 0009 — Static dashboard behind Cloudflare Access

**Status:** accepted (2026-10-19). Amended by ADR 0012 (M21): the Worker now runs code on `/api/*` for application tracking, and the page fetches that API.

## Context

The email digest is the only view of the results. It shows what is new, once, in a mailbox:
there is no way to browse the 125 canonical eligible and stretch jobs of the local DB, to sort
them by required years, to filter one department, or to look at the run funnel (fetched →
rejected by reason → eligible / strong / stretch) other than scrolling the public Actions log.
A web view was planned from the start (brief §17, "web app (later)") on one condition: only if
the digest stops being enough. It has.

Constraints: single user, public repo, SQLite in a private data repo refreshed once a day by
the workflow, no server anywhere, no secret or personal data in git or in the Actions log
(CLAUDE.md rule 11), no framework or build step unless a concrete problem requires one.

## Decision

1. **The dashboard is a static snapshot, not an application.** `job-match dashboard --out site`
   reads the DB after the daily run and writes `site/index.html` + `site/data.json`. The page is
   one file: CSS and JS inlined, the data embedded as a JSON block, no fetch, no framework, so it
   opens from `file://` as well as from a host. Filtering, sorting and the details rows run in
   the browser on ~130 jobs, which is nothing.
2. **The generator is the allow-list** (`dashboard/data.py`). Only named fields leave the DB:
   no job description, no `search_query`, no `by_keyword` (the profile's keywords), no profile
   at all (the command loads `settings.yaml` only). Required years are the parser's stored
   number or the gate's own stretch note, never recomputed from today's config. Links are kept
   only with an `http(s)` scheme.
3. **External text can never become markup.** The JSON block escapes every `<` as `<`
   (still valid JSON, so a title containing `</script>` or `<!--` survives `JSON.parse` intact),
   the script builds the DOM with `textContent`, links carry `rel="noopener noreferrer"`, and a
   `Content-Security-Policy` meta allows inline script and style only, no network. Tested with
   a seeded `</script><script>alert(1)</script><img onerror…>` title.
4. **Hosting: Cloudflare Worker with static assets, behind Cloudflare Access.** `wrangler.jsonc`
   names the existing Worker `job-match`, points `assets.directory` at `./site` and has no
   `main`: there is no code to run or secure on the server side. Access, configured in the
   Cloudflare dashboard on the production and preview URLs, is the whole authentication story.
   The daily workflow builds and deploys after the DB push, both steps `continue-on-error` and
   guarded like the push (`always() && steps.wal.outcome == 'success'`), so a failed deploy or a
   failed digest costs neither the digest nor the DB sync. Wrangler prints the Worker URL on
   stdout, so stdout is discarded; `site/` is gitignored and is never an Actions artifact.
5. **Design tokens come from `docs/design/DESIGN.md`** (dark canvas first, light via the inverse
   tokens, one lavender accent, two semantic data colours for strong and stretch), applied as a
   dense data table (13 px type, 36 px rows), responsive down to 390 px, honouring
   `prefers-reduced-motion`.

Alternatives, one line each: a Flask/FastAPI app reading SQLite (a server to run, patch and
authenticate, for one reader of a once-a-day snapshot); Cloudflare Pages (a second project when
the Worker already exists and Access already protects it); GitHub Pages (public, and the repo is
public); an Actions artifact (public download of personal data); a charts library (a CSS bar
funnel is enough).

## Consequences

- The dashboard is as fresh as the last successful daily run and is read-only: changes go
  through the CLI, the config and the next run.
- Two new GitHub secrets, `CLOUDFLARE_API_TOKEN` (Workers Scripts: Edit on the account) and
  `CLOUDFLARE_ACCOUNT_ID`. Check that Access is enabled on the Worker before adding them: the
  first `wrangler deploy` would otherwise serve the page publicly until Access is switched on.
- `site/index.html` embeds job titles, companies, scores and explanations: it is personal data,
  gitignored, and must never be attached to an issue or a PR.
- The Worker URL lives nowhere in the repo, the README or the logs.
- Every new field shown on the page is a deliberate line in `dashboard/data.py` and a test.
