"""`job-match apply` on local Greenhouse / Lever / Ashby forms (ADR 0023), no network.

Every page loads tests/fixtures/apply/guard.js, which records any press of a button or link
and any form submission: each test fails if the filler pressed Submit (or anything else).
A salary field is never filled in `mode: manuel`.
"""

from pathlib import Path

import pytest

from job_match.apply.config import (
    ApplyConfig,
    Benchmark,
    FixedAnswer,
    Remuneration,
    SalaryRange,
)
from job_match.apply.forms import Inputs
from job_match.apply.questions import load_questions
from job_match.apply.session import UNSUPPORTED, fill_page

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "apply"
QUESTIONS = load_questions(ROOT / "config" / "apply_questions.yaml")

GREENHOUSE = "https://job-boards.greenhouse.io/acme/jobs/123"
LEVER = "https://jobs.lever.co/acme/0f1e2d3c"
ASHBY = "https://jobs.ashbyhq.com/acme/7a6b5c4d"
OTHER = "https://careers.example.com/jobs/1"
PAGES = {
    "job-boards.greenhouse.io": "greenhouse.html",
    "jobs.lever.co": "lever.html",
    "jobs.ashbyhq.com": "ashby.html",
    "careers.example.com": "other.html",
}

CONTACT = {
    "first_name": "Jeanne",
    "last_name": "Testeur",
    "email": "jeanne@example.com",
    "phone": "+33 6 00 00 00 00",
    "linkedin": "linkedin.com/in/jeanne-t",
    "github": "github.com/jeanne-t",
    "title": "DevOps",
    "location": "Paris",
}
KIT = [
    {
        "key": "motivation",
        "label": "Motivation (courte)",
        "text": "Ce poste prolonge mon alternance.",
        "copy": True,
    },
    {
        "key": "why_company",
        "label": "Pourquoi cette entreprise",
        "text": "Acme construit une plateforme cloud.",
        "copy": True,
    },
    {
        "key": "availability",
        "label": "Disponibilité",
        "text": "Disponible immédiatement",
        "copy": True,
    },
    {"key": "mobility", "label": "Mobilité", "text": "Mobile en France", "copy": True},
    {"key": "notice", "label": "Préavis", "text": "Aucun préavis", "copy": True},
    {
        "key": "salary",
        "label": "Prétentions salariales",
        "mode": "manuel",
        "text": None,
        "copy": False,
        "benchmark": {"zone": "Île-de-France", "text": "42–48 k€ brut annuel"},
    },
]
FIXED = [
    FixedAnswer("Autorisation de travail", ["authorized to work"], "Yes"),
    FixedAnswer("Permis", ["driving licence"], "Yes"),
]
REPERES = [Benchmark("Île-de-France", "42–48 k€ brut annuel", ["paris"])]
MANUEL = ApplyConfig(
    remuneration=Remuneration(mode="manuel", reperes=REPERES), reponses_fixes=FIXED
)
FOURCHETTE = ApplyConfig(
    remuneration=Remuneration(
        mode="fourchette", fourchette=SalaryRange(40000, 46000), reperes=REPERES
    ),
    reponses_fixes=FIXED,
)
FOURCHETTE_KIT = [i for i in KIT if i["key"] != "salary"] + [
    {
        "key": "salary",
        "label": "Prétentions salariales",
        "mode": "fourchette",
        "copy": True,
        "text": "40 000 – 46 000 € brut annuel",
        "range": {"min": 40000, "max": 46000},
        "benchmark": {"zone": "Île-de-France", "text": "42–48 k€ brut annuel"},
    }
]
SALARY_FIELDS = {
    "greenhouse": "#question_5",
    "lever": "select[name='cards[a][field1]']",
    "ashby": "#f_comp",
}


@pytest.fixture
def files(tmp_path):
    cv = tmp_path / "CV_Jeanne_Testeur_Acme.pdf"
    letter = tmp_path / "Lettre_Jeanne_Testeur_Acme.pdf"
    cv.write_bytes(b"%PDF-1.7 cv")
    letter.write_bytes(b"%PDF-1.7 letter")
    return {"resume": cv, "cover_letter": letter}


@pytest.fixture
def form_page(browser):
    """A page whose every request is answered from the fixtures; anything else is aborted.
    `page.posts` collects the non-GET requests (a submission would be one)."""
    pages = []

    def _open(page_file=None):
        ctx = browser.new_context()
        page = ctx.new_page()
        page.posts = []

        def handle(route):
            req = route.request
            if req.method != "GET":
                page.posts.append(req.url)
                return route.abort()
            url = req.url
            host = url.split("/")[2]
            if url.endswith("/guard.js"):
                return route.fulfill(
                    path=str(FIXTURES / "guard.js"), content_type="text/javascript"
                )
            name = page_file or PAGES.get(host)
            if name and "/recaptcha/" not in url:
                return route.fulfill(path=str(FIXTURES / name), content_type="text/html")
            if "/recaptcha/" in url:
                return route.fulfill(
                    body="<html><body>challenge</body></html>", content_type="text/html"
                )
            return route.abort()

        page.route("**/*", handle)
        pages.append(ctx)
        return page

    yield _open
    for ctx in pages:
        ctx.close()


def _run(page, url, apply=MANUEL, kit=KIT, files=None, waits=None):
    said = []
    waited = waits if waits is not None else []
    inputs = Inputs(
        contact=CONTACT,
        kit=kit,
        apply=apply,
        files=files or {},
        letter_text="Madame, Monsieur,\n\nTexte.",
    )
    report = fill_page(
        page, url, QUESTIONS, inputs, waited.append, said.append, form_timeout_ms=3000
    )
    return report, said


def _assert_nothing_pressed(page):
    guard = page.evaluate("window.__jm")
    assert guard["clicks"] == [], f"the filler pressed {guard['clicks']}"
    assert guard["submits"] == 0, "the form was submitted"
    assert page.posts == [], f"a request was sent: {page.posts}"


def _value(page, selector):
    return page.eval_on_selector(selector, "el => el.value")


def _files(page, selector):
    return page.eval_on_selector(selector, "el => Array.from(el.files).map(f => f.name)")


def test_the_guard_sees_a_submit_click(form_page):
    """The detector the other tests rely on: pressing Submit is caught."""
    page = form_page()
    page.goto(GREENHOUSE)
    page.evaluate("document.querySelector('form').noValidate = true")  # required fields are empty
    page.click("#submit_app")
    guard = page.evaluate("window.__jm")
    assert guard["clicks"] == ["Submit application"]
    assert guard["submits"] == 1


def test_greenhouse_fills_known_fields_and_leaves_the_rest(form_page, files):
    page = form_page()
    report, said = _run(page, GREENHOUSE, files=files)
    assert report.ats == "greenhouse"
    assert _value(page, "#first_name") == "Jeanne"
    assert _value(page, "#last_name") == "Testeur"
    assert _value(page, "#email") == "jeanne@example.com"
    assert _value(page, "#phone") == "+33 6 00 00 00 00"
    assert _files(page, "#resume") == ["CV_Jeanne_Testeur_Acme.pdf"]
    assert _files(page, "#cover_letter") == ["Lettre_Jeanne_Testeur_Acme.pdf"]
    assert _value(page, "#question_1") == "https://linkedin.com/in/jeanne-t"
    assert _value(page, "#question_2") == "Acme construit une plateforme cloud."
    assert _value(page, "#question_3") == "Aucun préavis"
    assert _value(page, "#question_4") == "Yes"
    # unknown, sensitive, consent: empty, outlined, listed
    for sel in ("#question_5", "#question_6", "#gender", "#disability_status"):
        assert _value(page, sel) == "", sel
        assert page.get_attribute(sel, "data-jm-state"), f"{sel} is not highlighted"
    assert not page.is_checked("#gdpr")
    left = dict(report.left)
    assert left["How did you hear about this job?"] == "question inconnue"
    assert left["Gender"] == "question sensible, jamais remplie"
    assert left["I agree to the privacy policy"] == "case de consentement, à cocher toi-même"
    assert any(line.startswith("Formulaire greenhouse") for line in said)
    _assert_nothing_pressed(page)


def test_lever_fills_on_the_apply_page_and_never_writes_my_name_in_current_company(
    form_page, files
):
    page = form_page()
    report, _ = _run(page, LEVER, files=files)
    assert page.url.endswith("/0f1e2d3c/apply")
    assert _value(page, "input[name=name]") == "Jeanne Testeur"
    assert _value(page, "input[name=org]") == ""
    assert _value(page, "input[name='urls[GitHub]']") == "https://github.com/jeanne-t"
    assert _value(page, "input[name='cards[a][field0]']") == "Disponible immédiatement"
    assert _value(page, "textarea[name=comments]") == "Ce poste prolonge mon alternance."
    assert _files(page, "input[name=resume]") == ["CV_Jeanne_Testeur_Acme.pdf"]
    assert _value(page, "select[name='eeo[race]']") == ""
    assert not page.is_checked("input[name='consent[marketing]']")
    assert ("Current company", "question inconnue") in report.left
    _assert_nothing_pressed(page)


def test_ashby_waits_for_the_app_then_fills_radios_without_pressing_anything(form_page, files):
    page = form_page()
    report, _ = _run(page, ASHBY, files=files)
    assert page.url.endswith("/application")
    assert _value(page, "#_systemfield_name") == "Jeanne Testeur"
    assert _value(page, "#f_why") == "Ce poste prolonge mon alternance."
    assert _files(page, "#_systemfield_resume") == ["CV_Jeanne_Testeur_Acme.pdf"]
    assert page.is_checked("input[name=f_lic][value=yes]")
    assert not page.is_checked("input[name=f_reloc][value=yes]")
    assert not page.is_checked("input[name=f_reloc][value=no]")
    assert _value(page, "#f_pron") == ""
    assert _value(page, "#f_fav") == ""
    left = dict(report.left)
    assert left["Are you willing to relocate?"].startswith("aucune option ne correspond")
    assert left["Pronouns"] == "question sensible, jamais remplie"
    _assert_nothing_pressed(page)


@pytest.mark.parametrize(
    "ats,url", [("greenhouse", GREENHOUSE), ("lever", LEVER), ("ashby", ASHBY)]
)
def test_manuel_never_fills_a_salary_field_and_shows_the_benchmark(form_page, files, ats, url):
    page = form_page()
    report, said = _run(page, url, files=files)
    sel = SALARY_FIELDS[ats]
    assert _value(page, sel) == "", f"{ats}: a salary field was filled in mode manuel"
    assert page.get_attribute(sel, "data-jm-state") == "#dc2626"
    assert "Île-de-France : 42–48 k€" in (page.get_attribute(sel, "title") or "")
    assert any("Île-de-France : 42–48 k€ brut annuel" in n for n in report.notes)
    assert any("42–48 k€" in line for line in said)
    _assert_nothing_pressed(page)


def test_manuel_leaves_salary_empty_even_when_the_kit_carries_a_range(form_page, files):
    """The kit cannot override apply.yaml: in manuel, a range smuggled into the kit is ignored."""
    page = form_page()
    report, _ = _run(
        page,
        GREENHOUSE,
        apply=MANUEL,
        kit=[{**i, "mode": "manuel"} if i["key"] == "salary" else i for i in FOURCHETTE_KIT],
        files=files,
    )
    assert _value(page, "#question_5") == ""
    _assert_nothing_pressed(page)


def test_fourchette_fills_the_range_and_picks_the_option_inside_it(form_page, files):
    page = form_page()
    _run(page, GREENHOUSE, apply=FOURCHETTE, kit=FOURCHETTE_KIT, files=files)
    assert _value(page, "#question_5") == "40 000 – 46 000 € brut annuel"
    _assert_nothing_pressed(page)
    page = form_page()
    _run(page, LEVER, apply=FOURCHETTE, kit=FOURCHETTE_KIT, files=files)
    assert (
        page.eval_on_selector(
            "select[name='cards[a][field1]']", "el => el.options[el.selectedIndex].text"
        )
        == "40-45k"
    )
    page = form_page()
    report, _ = _run(page, ASHBY, apply=FOURCHETTE, kit=FOURCHETTE_KIT, files=files)
    assert _value(page, "#f_comp") == ""  # one figure asked: not mine to choose
    _assert_nothing_pressed(page)


def test_an_unknown_ats_is_not_supported_and_the_page_stays_untouched(form_page):
    page = form_page()
    report, said = _run(page, OTHER)
    assert report is None
    assert UNSUPPORTED in said
    assert _value(page, "#e") == ""
    _assert_nothing_pressed(page)


def test_a_captcha_pauses_for_me_then_the_fill_goes_on(form_page):
    page = form_page("captcha.html")
    waits = []

    def solve(prompt):
        waits.append(prompt)
        page.evaluate("document.querySelector('iframe').remove()")

    said = []
    inputs = Inputs(contact=CONTACT, kit=KIT, apply=MANUEL, files={})
    report = fill_page(
        page, GREENHOUSE, QUESTIONS, inputs, solve, said.append, form_timeout_ms=3000
    )
    assert len(waits) == 1
    assert any(s.startswith("CAPTCHA détecté : à toi") for s in said)
    assert _value(page, "#email") == "jeanne@example.com"
    assert report is not None
    _assert_nothing_pressed(page)


def test_a_sign_in_page_pauses_and_no_password_is_ever_written(form_page):
    page = form_page()
    page.goto(OTHER)
    page.set_content(
        "<form><label for=u>Email</label><input id=u type=email>"
        "<label for=p>Password</label><input id=p type=password>"
        "<button type=submit>Sign in</button></form>"
    )
    from job_match.apply.forms import blocker, fill_form

    assert blocker(page) == "login"
    report = fill_form(
        page, QUESTIONS, Inputs(contact=CONTACT, kit=KIT, apply=MANUEL, files={}), "greenhouse"
    )
    assert _value(page, "#p") == ""
    assert ("Password", "mot de passe : jamais rempli") in report.left


ENGLISH_FIXED = [
    FixedAnswer("Autorisation de travail", ["authorized to work"], "Oui"),
    FixedAnswer(
        "Sponsorship", ["visa sponsorship"], "Non", label_en="No, I do not need sponsorship"
    ),
    FixedAnswer("Permis", ["driving licence"], "Permis B"),
    FixedAnswer("Contrat", ["contract type"], "CDI"),
    FixedAnswer("Télétravail", ["work mode"], "Télétravail"),
]


def test_french_fixed_answers_pick_the_english_options(form_page):
    """oui/YES, non/No… (label_en), permis B/Driving Licence B, CDI/Permanent: case and accents
    ignored; an answer with no equivalent option (« Télétravail » vs « Fully remote ») stays
    empty and listed, never guessed."""
    page = form_page("english.html")
    apply = ApplyConfig(reponses_fixes=ENGLISH_FIXED)
    report, _ = _run(page, GREENHOUSE, apply=apply)

    def chosen(sel):
        return page.eval_on_selector(sel, "el => el.options[el.selectedIndex].text")

    assert chosen("#q_auth") == "YES"
    assert page.is_checked("input[name=q_visa][value='2']")
    assert not page.is_checked("input[name=q_visa][value='1']")
    assert chosen("#q_lic") == "Driving Licence B"
    assert chosen("#q_contract") == "Permanent"
    assert _value(page, "#q_work") == ""
    assert dict(report.left)["Preferred work mode"].startswith("aucune option ne correspond")
    _assert_nothing_pressed(page)


def test_without_label_en_non_still_finds_the_english_no(form_page):
    page = form_page("english.html")
    fixed = [FixedAnswer("Sponsorship", ["visa sponsorship"], "non")]
    _run(page, GREENHOUSE, apply=ApplyConfig(reponses_fixes=fixed))
    assert page.is_checked("input[name=q_visa][value='2']")  # "no …" via the oui/non table
    _assert_nothing_pressed(page)
