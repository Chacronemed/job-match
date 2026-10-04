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


# ---------------------------------------------------------------------------
# normalize_article_url (dedup key for articles)
# ---------------------------------------------------------------------------

def test_article_url_strips_tracking_slash_fragment_and_lowercases_host():
    from job_match.normalization.url import normalize_article_url

    raw = "https://WWW.Maddyness.com/2026/10/02/acme-leve/?utm_source=rss&utm_medium=feed#top"
    assert normalize_article_url(raw) == "https://www.maddyness.com/2026/10/02/acme-leve"


def test_article_url_variants_share_one_key():
    from job_match.normalization.url import normalize_article_url

    a = normalize_article_url("https://www.frenchweb.fr/elevenlabs-valorisee/463756")
    b = normalize_article_url("  https://www.frenchweb.fr/elevenlabs-valorisee/463756/ ")
    c = normalize_article_url("https://www.frenchweb.fr/elevenlabs-valorisee/463756?ref=twitter")
    assert a == b == c


def test_article_url_keeps_path_case_and_functional_params():
    from job_match.normalization.url import normalize_article_url

    out = normalize_article_url("https://x.test/Article/ID-42?page=2")
    assert out == "https://x.test/Article/ID-42?page=2"


def test_article_url_root_path_is_kept():
    from job_match.normalization.url import normalize_article_url

    assert normalize_article_url("https://x.test/") == "https://x.test/"
