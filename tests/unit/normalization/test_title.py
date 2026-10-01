import pytest

from job_match.normalization.title import normalize_title


@pytest.mark.parametrize("inp,expected", [
    ("DevOps Engineer H/F", "devops engineer"),
    ("Ingénieur DevOps (H/F)", "ingenieur devops"),
    ("DevOps Engineer F/H", "devops engineer"),
    ("Site Reliability Engineer - CDI", "site reliability engineer"),
    ("Stage DevOps", "devops"),              # "stage" removed
    ("Alternance Cloud", "cloud"),  # "alternance" is contract noise and is removed
    ("DevOps M/W/D", "devops"),
    ("Senior DevOps HF", "senior devops"),
])
def test_normalize_title(inp, expected):
    assert normalize_title(inp) == expected


def test_preserves_meaningful_content():
    result = normalize_title("Ingénieur Infrastructure Cloud H/F")
    assert "infrastructure" in result
    assert "cloud" in result
    assert "h f" not in result
