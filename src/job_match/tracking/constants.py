"""Application tracking enums, shared by the D1 schema, the Worker and the dashboard.

`tests/unit/tracking/test_enums.py` checks that the D1 migration's CHECK lists, the Worker,
the dashboard script and these tuples name the same values.
"""

import re

STATUSES = ("to_review", "to_apply", "applied", "interview", "rejected", "ignored")
LABELS = ("good_fit", "off_topic", "too_senior", "missing_skill")
# Jobs still waiting for me: shown in the digest. Every other status is handled.
ACTIVE_STATUSES = ("to_review", "to_apply")
# A follow-up stops mattering once the application is closed either way.
NO_FOLLOW_UP_STATUSES = ("rejected", "ignored")

JOB_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}:[A-Za-z0-9._-]{1,64}\Z")
# A skill override's name: a lowercase vocabulary term ("gitlab ci", "c#", "node.js").
SKILL_MAX = 40
SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9+#./ -]{0,39}\Z")
NOTE_MAX = 2000
URL_MAX = 500


def job_key(source: str, source_job_id: str) -> str:
    """`france_travail:123ABCD`: the natural key, never the SQLite surrogate id."""
    return f"{source}:{source_job_id}"
