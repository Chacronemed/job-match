import pytest

from job_match.domain.models import ExperienceStatus
from job_match.experience.parser import infer_seniority_min, parse

# ---------------------------------------------------------------------------
# Table-driven cases
# ---------------------------------------------------------------------------

_CASES = [
    # (text, status, min_years, max_years)
    # Range patterns
    ("2 à 5 ans d'expérience", ExperienceStatus.ELIGIBLE, 2.0, 5.0),
    ("2-5 years", ExperienceStatus.ELIGIBLE, 2.0, 5.0),
    ("2 to 5 years", ExperienceStatus.ELIGIBLE, 2.0, 5.0),
    # Explicit minimum
    ("au moins 3 ans d'expérience", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("at least 3 years of experience", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("minimum 3 years experience required", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("au minimum 2 ans", ExperienceStatus.ELIGIBLE, 2.0, None),
    # Plus notation
    ("3+ ans d'expérience requis", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("3+ years", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("5+ years of DevOps experience", ExperienceStatus.ELIGIBLE, 5.0, None),
    # Plain numeric
    ("3 ans d'expérience", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("3 years of experience", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("3 years experience", ExperienceStatus.ELIGIBLE, 3.0, None),
    ("Vous justifiez de 5 ans d'expérience en DevOps", ExperienceStatus.ELIGIBLE, 5.0, None),
    # Written numbers (FR)
    ("deux ans d'expérience", ExperienceStatus.ELIGIBLE, 2.0, None),
    ("cinq ans d'expérience minimum", ExperienceStatus.ELIGIBLE, 5.0, None),
    # Written numbers (EN)
    ("two years of experience", ExperienceStatus.ELIGIBLE, 2.0, None),
    ("five years of experience required", ExperienceStatus.ELIGIBLE, 5.0, None),
    # Maximum only
    ("jusqu'à 2 ans d'expérience", ExperienceStatus.ELIGIBLE, None, 2.0),
    ("up to 2 years", ExperienceStatus.ELIGIBLE, None, 2.0),
    ("moins de 3 ans", ExperienceStatus.ELIGIBLE, None, 3.0),
    # Ambiguous → UNKNOWN
    ("première expérience souhaitée", ExperienceStatus.UNKNOWN, None, None),
    ("Profil débutant accepté", ExperienceStatus.UNKNOWN, None, None),
    ("junior developer", ExperienceStatus.UNKNOWN, None, None),
    ("entry-level position", ExperienceStatus.UNKNOWN, None, None),
    ("solid experience required", ExperienceStatus.UNKNOWN, None, None),
    ("significant experience in cloud", ExperienceStatus.UNKNOWN, None, None),
    # Nothing → NOT_MENTIONED
    ("DevOps engineer at Acme", ExperienceStatus.NOT_MENTIONED, None, None),
    ("", ExperienceStatus.NOT_MENTIONED, None, None),
]


@pytest.mark.parametrize(("text", "status", "min_years", "max_years"), _CASES)
def test_parse_cases(text, status, min_years, max_years):
    result = parse(text)
    assert result.status == status
    assert result.min_years == min_years
    assert result.max_years == max_years


# ---------------------------------------------------------------------------
# Targeted tests
# ---------------------------------------------------------------------------


def test_parse_smallest_minimum():
    # Multiple mentions — should take the smallest min_years
    result = parse("5 ans minimum, idéalement 3 ans d'expérience en infrastructure")
    assert result.status == ExperienceStatus.ELIGIBLE
    assert result.min_years == 3.0


def test_parse_false_positive_company_age_alone():
    # "créée en 2018" with no experience mention → NOT_MENTIONED
    result = parse("Société créée en 2018, rejoignez notre équipe.")
    assert result.status == ExperienceStatus.NOT_MENTIONED


def test_parse_false_positive_stripped_leaves_real_exp():
    # Company founding year is stripped; the real requirement survives
    result = parse("fondée en 2010, nous cherchons un profil 3+ ans d'expérience DevOps")
    assert result.status == ExperienceStatus.ELIGIBLE
    assert result.min_years == 3.0


def test_parse_ambiguous_overridden_by_numeric():
    # "junior" is present but a numeric mention exists — ELIGIBLE wins
    result = parse("junior ou confirmé avec 2 ans d'expérience accepté")
    assert result.status == ExperienceStatus.ELIGIBLE
    assert result.min_years == 2.0


def test_parse_evidence_populated_on_numeric_match():
    result = parse("au moins 4 ans d'expérience")
    assert result.status == ExperienceStatus.ELIGIBLE
    assert result.evidence is not None
    assert len(result.evidence) > 0


def test_parse_evidence_populated_on_ambiguous():
    result = parse("première expérience bienvenue")
    assert result.status == ExperienceStatus.UNKNOWN
    assert result.evidence is not None


def test_parse_status_eligible_for_any_numeric():
    for text in ("1 an", "10 years", "3+ ans", "at least 2 years"):
        assert parse(text).status == ExperienceStatus.ELIGIBLE


def test_parse_range_evidence_contains_both_bounds():
    result = parse("expérience de 2 à 5 ans requise")
    assert result.min_years == 2.0
    assert result.max_years == 5.0
    assert "2" in (result.evidence or "")
    assert "5" in (result.evidence or "")


# ---------------------------------------------------------------------------
# infer_seniority_min
# ---------------------------------------------------------------------------

_SMAP = {"junior": 0, "débutant": 0, "confirmé": 3, "confirmée": 3, "senior": 5, "expert": 7, "lead": 5}


def test_seniority_senior_title():
    assert infer_seniority_min("Senior DevOps Engineer", "", _SMAP) == 5


def test_seniority_expert_in_description():
    assert infer_seniority_min("DevOps", "We need an expert engineer with strong IaC skills", _SMAP) == 7


def test_seniority_confirme_title():
    assert infer_seniority_min("Ingénieur DevOps Confirmé", "", _SMAP) == 3


def test_seniority_junior_returns_zero():
    assert infer_seniority_min("Junior Developer", "", _SMAP) == 0


def test_seniority_no_keyword_returns_none():
    assert infer_seniority_min("DevOps Engineer", "Looking for someone with cloud skills", _SMAP) is None


def test_seniority_multiple_keywords_takes_highest():
    # "senior" (5) and "expert" (7) → 7
    assert infer_seniority_min("Senior Expert DevOps", "", _SMAP) == 7


def test_seniority_case_insensitive():
    assert infer_seniority_min("SENIOR DEVOPS", "", _SMAP) == 5


def test_seniority_no_partial_word_match():
    # "seniority" must not match "senior"; "expertise" must not match "expert"
    assert infer_seniority_min("", "requires seniority and deep expertise", _SMAP) is None


def test_seniority_empty_map_returns_none():
    assert infer_seniority_min("Senior DevOps", "expert needed", {}) is None


def test_seniority_lead_word_boundary():
    assert infer_seniority_min("Tech Lead", "", _SMAP) == 5
    # "leading" must NOT match "lead"
    assert infer_seniority_min("", "leading a team of engineers", _SMAP) is None
