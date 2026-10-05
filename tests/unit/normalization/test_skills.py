from job_match.normalization.skills import (
    contains_term,
    matches_skill,
    skill_forms,
    title_keyword,
)


def test_skill_forms_include_aliases():
    assert skill_forms("Kubernetes", {"kubernetes": ["k8s"]}) == ["kubernetes", "k8s"]


def test_contains_term_is_whole_term():
    assert contains_term("CI/CD avec GitLab", "ci/cd")
    assert not contains_term("javascript", "java")


def test_matches_skill_via_alias():
    assert matches_skill("Expérience K8S requise", "kubernetes", {"kubernetes": ["k8s"]})


def test_title_keyword_prefix_and_accent_insensitive():
    keywords = ["infra", "système", "devops"]
    assert title_keyword("Ingénieur Infrastructure H/F", keywords) == "infra"
    assert title_keyword("Administrateur SYSTEMES et réseaux", keywords) == "système"
    assert title_keyword("Ingénieur DevOps", keywords) == "devops"


def test_title_keyword_requires_word_start():
    assert title_keyword("Réceptionniste en hôtellerie", ["ops", "infra"]) is None
    assert title_keyword("Chef de rayon", ["sre"]) is None  # no "sre" at a word start
