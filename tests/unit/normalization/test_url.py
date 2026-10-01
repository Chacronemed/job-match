from job_match.normalization.url import normalize_url


def test_strips_utm_params():
    url = "https://example.com/job/123?utm_source=indeed&utm_medium=organic"
    assert normalize_url(url) == "https://example.com/job/123"


def test_keeps_functional_params():
    url = "https://example.com/jobs?page=2&q=devops"
    result = normalize_url(url)
    assert "page=2" in result
    assert "q=devops" in result


def test_strips_ref_and_fbclid():
    url = "https://example.com/j/1?ref=linkedin&fbclid=abc"
    assert normalize_url(url) == "https://example.com/j/1"


def test_mixed_params():
    url = "https://example.com/j/1?id=42&utm_campaign=spring"
    result = normalize_url(url)
    assert "id=42" in result
    assert "utm_campaign" not in result


def test_malformed_url_returned_as_is():
    bad = "not a url %%"
    assert normalize_url(bad) == bad
