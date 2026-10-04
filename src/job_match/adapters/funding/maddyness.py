from job_match.adapters.funding.rss import RssFundingSource


class MaddynessSource(RssFundingSource):
    name = "maddyness"
    FEED_URL = "https://www.maddyness.com/feed/"
