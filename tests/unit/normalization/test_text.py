import pytest

from job_match.normalization.text import normalize_text


@pytest.mark.parametrize("inp,expected", [
    ("Café", "cafe"),
    ("expérience", "experience"),
    ("  Hello   World  ", "hello world"),
    ("CI/CD pipeline", "ci cd pipeline"),
    ("K8S", "k8s"),
    ("(H/F)", "h f"),
    ("", ""),
    ("NŒUD", "nœud"),  # Œ is a ligature; NFKD doesn't expand it to oe
])
def test_normalize_text(inp, expected):
    assert normalize_text(inp) == expected


def test_accent_folding():
    assert normalize_text("ingénieur") == "ingenieur"
    assert normalize_text("réseaux") == "reseaux"


def test_punctuation_stripped():
    result = normalize_text("foo.bar-baz!qux")
    assert "." not in result
    assert "!" not in result
    assert "-" not in result


def test_underscore_kept():
    # \w includes underscore; useful for identifiers
    assert "_" in normalize_text("my_var")
