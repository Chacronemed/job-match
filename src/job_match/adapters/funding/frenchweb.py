from job_match.adapters.funding.rss import RssFundingSource


class FrenchWebSource(RssFundingSource):
    name = "frenchweb"
    FEED_URL = "https://www.frenchweb.fr/feed"
