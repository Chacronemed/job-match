# ADR 0029: Talentsoft career sites through their offers RSS feed

**Status:** accepted, 2026-11-20

## Context

Air France-KLM is a target company (`config/companies.yaml`, IT centre in Valbonne, Toulouse
and Roissy) whose offers never reach the pipeline: `recrutement.airfrance.com` is a Talentsoft
(Cegid) front office, and Talentsoft has no public JSON board. Its API needs a client key, and
ADR 0020 forbids reading the HTML pages.

The site does publish something meant for machines: `/offre-de-emploi/tous-les-flux-rss.aspx`
lists RSS feeds, the unfiltered one being `/handlers/offerRss.ashx?LCID=1036`. Measured on
2026-11-20 (one GET): RSS 2.0, the **20 newest offers**, each with a link carrying `idOffre`,
three categories (job family, contract, site), a title prefixed by the offer reference, a
publication date, and a description of 1 900 to 4 800 characters (Métier, Type de contrat,
Description du poste, Site, Niveau d'études). The 20 items covered 3.2 days, so a daily run
sees every offer. The site's `robots.txt` is empty.

Crédit Agricole CIB, Bouygues Telecom, SFR and Naval Group are also Talentsoft sites
(`config/companies_detected.yaml`); none of them was checked here.

## Decision

A sixth board type, `talentsoft`, in the existing `ats` source (ADR 0020), not a new source:

- `config/ats_boards.yaml`: `{company: Air France, ats: talentsoft, slug: <host>}`. The slug is
  the career site's host, called as is, so the loader only accepts a plain lowercase host name
  (no path, no port, no IP address).
- `adapters/jobs/talentsoft.py` reads the feed with `feedparser` (already in the stack for the
  funding feeds) and maps an item: title without its reference prefix, `idOffre` as the id,
  the three categories as family / contract hint / location when there are exactly three (else
  the location stays empty: nothing is guessed), the description through `html_to_text`.
- `AtsBoardSource` makes the call: one GET per board and run, no detail call, the same pacing,
  error handling, request stats and `source_job_id` (`talentsoft:<host>:<idOffre>`) as every
  other board. A body that is not a feed is a failed board, logged and skipped.
- Downstream nothing changes: same normalization, experience gate, location gate, dedup with
  France Travail, scoring. The location is whatever the feed says ("Valbonne", an address with
  its postal code); a site code the gate cannot read ("VLR") is rejected like any unreadable
  location of a non-France-Travail source. No country is appended.
- **Closure:** the feed only shows its newest offers, so its listing is never complete. An
  offer still in the feed is OPEN; one that left it is UNKNOWN, never CLOSED. Nothing is
  written and the age cut-off (`jobs.max_age_days`) hides it in the end.

## Alternatives considered

- **Reading the offer pages** (`detailoffre.aspx`): HTML scraping, excluded by ADR 0020.
- **Talentsoft's REST API:** needs credentials issued to the customer, not to us.
- **A separate `talentsoft` source:** a second class, a second `by_company` counter, a second
  entry in the dashboard's Source filter, for one GET. The board type costs a mapper.
- **Filtered feeds** (`Rss_JobCountry`, `Rss_Contract`, a job family) to see more than 20
  offers or only the French ones: the filter ids are per-site numbers that would have to be
  discovered and configured per board. Not needed while 20 offers cover three days.
- **Appending "France" to every location:** the feed is the French-language site but also
  carries offers abroad. Unknown stays unknown.

## Consequences

- One more call per run; Air France appears in « Pages carrière par entreprise ».
- An eligible offer that left the feed stays UNKNOWN at every closure check until it ages
  out (at most 45 days): it counts in the run's `errors` (unclear answers). With six offers a
  day, most of them aircraft maintenance, few are eligible; if the count grows, the next step
  is a filtered feed per job family.
- A day with more than 20 new offers would lose the oldest ones. Not seen (about 6 a day).
- Another Talentsoft site is one YAML line once its feed is checked by hand. Not every site
  enables the feed, and the category order is the site's own configuration: check it first.
- The fixture `tests/fixtures/talentsoft_feed.xml` is made up (example.com, invented offers).
