"""private/apply.yaml parsing and the question classifier (ADR 0023). Synthetic values only."""

from pathlib import Path

import pytest

from job_match.apply.config import ApplyConfig, FixedAnswer, load_apply, parse_apply, to_json
from job_match.apply.forms import application_url, detect_ats, salary_option
from job_match.apply.questions import Field, load_questions
from job_match.config.schema import ConfigError

ROOT = Path(__file__).resolve().parents[3]
Q = load_questions(ROOT / "config" / "apply_questions.yaml")
APPLY = ApplyConfig(reponses_fixes=[FixedAnswer("Travail", ["authorized to work"], "Yes")])


def kind(label, type_="text", tag="input", name="", apply=APPLY):
    return Q.classify(Field(ref="0", tag=tag, type=type_, label=label, name=name), apply).category


def test_missing_file_means_manuel_and_nothing_fixed(tmp_path):
    cfg = load_apply(tmp_path / "apply.yaml")
    assert cfg.remuneration.mode == "manuel"
    assert cfg.reponses_fixes == []


def test_a_full_file_parses():
    cfg = parse_apply(
        {
            "remuneration": {
                "mode": "fourchette",
                "fourchette": {"min": 40000, "max": 46000},
                "reperes": [{"zone": "IDF", "match": ["paris"], "texte": "42-48 k"}],
            },
            "preavis": "Aucun",
            "mobilite": "France",
            "reponses_fixes": [{"label": "Permis", "match": ["permis"], "reponse": "Oui"}],
        }
    )
    assert cfg.remuneration.fourchette.min == 40000
    assert cfg.remuneration.fourchette.devise == "€"
    assert cfg.reponses_fixes[0].reponse == "Oui"
    assert '"min": 40000' in to_json(cfg)  # fourchette: the range is the point


@pytest.mark.parametrize(
    "raw,message",
    [
        ({"remuneration": {"mode": "auto"}}, "mode must be one of"),
        ({"remuneration": {"mode": "fourchette"}}, "needs remuneration.fourchette"),
        ({"remuneration": {"fourchette": {"min": 50000, "max": 40000}}}, "min is above max"),
        ({"remuneration": {"fourchette": {"min": "40k", "max": 45000}}}, "positive integer"),
        ({"reponses_fixes": [{"label": "x", "match": [], "reponse": "y"}]}, "at least one word"),
        ({"salaire": 1}, "unknown keys"),
    ],
)
def test_bad_files_are_refused(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_apply(raw)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("First Name*", "first_name"),
        ("Nom de famille", "last_name"),
        ("Full name ✱", "full_name"),
        ("Name", "full_name"),
        ("Company name", "unknown"),
        ("Nom de l'entreprise", "unknown"),
        ("E-mail", "email"),
        ("Téléphone", "phone"),
        ("LinkedIn Profile", "linkedin"),
        ("Why do you want to work at Acme?", "why_company"),
        ("Pourquoi ce poste ?", "motivation"),
        ("Date de disponibilité", "availability"),
        ("Préavis", "notice"),
        ("Êtes-vous prêt à déménager ?", "mobility"),
        ("Are you authorized to work in France?", "fixed"),
        ("Prétentions salariales", "salary"),
        ("Salary expectations (gross)", "salary"),
        ("Gender", "sensitive"),
        ("Êtes-vous en situation de handicap (RQTH) ?", "sensitive"),
        ("What is your age?", "sensitive"),
        ("How did you hear about us?", "unknown"),
    ],
)
def test_labels(label, expected):
    assert kind(label) == expected


def test_sensitive_wins_over_everything_and_checkboxes_are_never_answers():
    assert kind("Gender (why do you want to work at Acme)") == "sensitive"
    assert kind("I agree to the privacy policy", type_="checkbox") == "consent"
    assert kind("Are you authorized to work in France?", type_="checkbox") == "unknown"
    assert kind("Password", type_="password") == "password"
    assert kind("Resume/CV", type_="file") == "resume"
    assert kind("Cover Letter", type_="file") == "cover_letter"
    assert kind("Cover Letter", tag="textarea", type_="") == "cover_letter"
    assert kind("Portfolio", type_="file") == "unknown"
    assert kind("Salary expectations", tag="select", type_="") == "salary"


def test_ats_detection_and_application_pages():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert detect_ats("https://evil-lever.co.example.com/x") is None
    assert detect_ats("https://careers.acme.fr/jobs/1") is None
    assert (
        application_url("https://jobs.lever.co/acme/abc?lever-source=x", "lever")
        == "https://jobs.lever.co/acme/abc/apply?lever-source=x"
    )
    assert application_url("https://jobs.lever.co/acme/abc/apply", "lever").endswith("/abc/apply")
    assert application_url("https://jobs.ashbyhq.com/acme/abc", "ashby").endswith(
        "/abc/application"
    )
    assert application_url("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse").endswith(
        "/jobs/1"
    )


def test_salary_option_only_inside_the_range():
    options = ("Select", "30-35k", "40-45k", "50 000 - 60 000 €")
    assert salary_option(options, 40000, 46000) == 2
    assert salary_option(options, 52000, 70000) is None  # 50 000 is below my minimum
    assert salary_option(options, 30000, 60000) is None  # several: not mine to choose


def test_label_en_is_optional_and_parsed():
    cfg = parse_apply(
        {
            "reponses_fixes": [
                {"label": "Visa", "match": ["sponsorship"], "reponse": "Non", "label_en": "No"},
                {"label": "Permis", "match": ["permis"], "reponse": "Oui"},
            ]
        }
    )
    assert cfg.reponses_fixes[0].label_en == "No"
    assert cfg.reponses_fixes[1].label_en == ""


def test_option_forms_are_bilingual_and_folded():
    assert Q.option_forms("Oui") == ["oui", "yes"]
    assert "driving licence b" in Q.option_forms("Permis B")
    assert Q.option_forms("CDI")[:2] == ["cdi", "permanent"]
    assert Q.option_forms("Non", "No, thanks")[:2] == ["non", "no thanks"]
    assert Q.option_forms("Télétravail")[0] == "teletravail"  # accents folded
    assert Q.option_forms("Bac+5") == ["bac 5"]  # no group: the answer only


def test_option_equivalents_must_be_groups(tmp_path):
    bad = tmp_path / "q.yaml"
    text = (ROOT / "config" / "apply_questions.yaml").read_text(encoding="utf-8")
    bad.write_text(text + '\n  - ["seul"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="option_equivalents"):
        load_questions(bad)
