"""Hiring-signal precision, multi-topic briefs and explicit country.

The brief below reproduces the structure of a real FrenchWeb daily brief (2026-10-05): the
Jaipur Robotics deal sits next to an unrelated paragraph about Anthropic "recruiting" a person.
Before the fix, Jaipur Robotics got hiring="recrutement" from that paragraph.
"""
from job_match.funding.extractor import extract_funding, is_brief, split_paragraphs

BRIEF_TITLE = (
    "POSITIVE se refinance pour poursuivre sa consolidation européenne / LIQUID NETWORK "
    "suspend ses transactions / H COMPANY n’a plus aucun de ses fondateurs"
)
ANTHROPIC_PARA = (
    "Matt Clifford quittera le 6 novembre la présidence d’Aria, l’agence britannique chargée "
    "de financer la recherche scientifique. Son recrutement à temps plein par Anthropic pour "
    "conduire les relations du groupe avec les gouvernements hors des États-Unis avait suscité "
    "les critiques de plusieurs parlementaires."
)
JAIPUR_HEADING = (
    "Jaipur Robotics lève 4,3 millions d’euros pour automatiser les usines de valorisation "
    "des déchets"
)
JAIPUR_PARA = (
    "La startup suisse Jaipur Robotics lève 4,3 millions d’euros en seed lors d’un tour mené "
    "par EquityPitcher Ventures et High-Tech Gründerfonds. Fondée en 2024, elle développe une "
    "plateforme de vision par ordinateur. Les fonds financeront son déploiement dans de "
    "nouvelles usines."
)
OTHER_DEAL_PARA = (
    "La startup suédoise Fluencify boucle un tour de pré-seed de 3,7 millions d’euros, mené "
    "par byFounders. Les fonds financeront des recrutements à Stockholm."
)
BRIEF_BODY = "\n".join([ANTHROPIC_PARA, JAIPUR_HEADING, JAIPUR_PARA, OTHER_DEAL_PARA])


# ---------------------------------------------------------------------------
# Hiring
# ---------------------------------------------------------------------------

def test_jaipur_brief_has_no_hiring_from_the_anthropic_paragraph():
    result = extract_funding(BRIEF_TITLE, BRIEF_BODY)
    assert result.company == "Jaipur Robotics"
    assert result.hiring is None
    assert "hiring" not in result.evidence


def test_bare_recruitment_noun_about_a_person_is_not_hiring():
    sentence = ("Acme lève 5 M€. Son recrutement à temps plein par Anthropic avait suscité "
                "des critiques.")
    assert extract_funding(sentence, "").hiring is None
    named = extract_funding("Acme lève 5 M€.", "Le recrutement de Jane Doe comme CTO.")
    assert named.hiring is None


def test_hiring_more_than_three_sentences_after_anchor_needs_a_tie_back():
    far = ("Acme lève 5 M€ auprès de Kima Ventures. Une phrase. Deux phrases. Trois phrases. "
           "Le secteur prévoit de recruter 20 ingénieurs.")
    assert extract_funding("Acme lève 5 M€", far).hiring is None  # no reference to Acme/raise
    close = "Acme lève 5 M€ auprès de Kima Ventures. Une phrase. On va recruter 20 ingénieurs."
    assert extract_funding("Acme lève 5 M€", close).hiring == "recruter 20 ingénieurs"


def test_hiring_in_another_paragraph_without_tie_back_is_ignored():
    body = "Acme lève 5 M€ auprès de Kima Ventures.\nLe marché prévoit de recruter 20 ingénieurs."
    assert extract_funding("Acme lève 5 M€", body).hiring is None


# Real sentences (2026-10-05) from single-topic articles: the "use of funds" paragraph sits
# far below the anchor and refers back to the raise or the company.
FAR_LEDE = ("{c} lève 7 millions d’euros auprès de Kima Ventures. Une phrase. Deux phrases. "
            "Trois phrases. Quatre phrases.")


def _far(company: str, sentence: str) -> str:
    return FAR_LEDE.format(c=company) + "\nUn paragraphe sans rapport.\n" + sentence


def test_single_topic_exception_accepts_sentences_referring_back():
    cases = {
        "PRIMO": ("Le financement doit permettre à l’entreprise de doubler ses effectifs et "
                  "d’accélérer son développement international.", "doubler ses effectifs"),
        "Hackuity": ("Le financement servira à recruter des équipes commerciales, à accélérer en "
                     "France et aux États-Unis.", "servira à recruter"),
        "Kheops": ("Kheops prévoit d’abord d’accélérer son déploiement en France et de renforcer "
                   "ses équipes.", "renforcer ses équipes"),
        "Lightspring": ("Elle prévoit maintenant de renforcer son équipe en recrutant notamment "
                        "dans la microfabrication.", "renforcer son équipe"),
        "Implicity": ("Les 35 millions d’euros doivent soutenir la R&D en France, tout en "
                      "finançant le recrutement d’équipes opérationnelles aux États-Unis.",
                      "finançant le recrutement d’équipes"),
    }
    for company, (sentence, phrase) in cases.items():
        result = extract_funding(f"{company} lève 7 M€", _far(company, sentence))
        assert result.hiring == phrase, company
        assert result.evidence["hiring"] == sentence


def test_single_topic_exception_never_applies_to_briefs():
    body = BRIEF_BODY + "\nJaipur Robotics prévoit de recruter 20 ingénieurs à Zurich."
    brief = extract_funding(BRIEF_TITLE, body.replace(JAIPUR_PARA, JAIPUR_PARA + " A. B. C. D."))
    assert brief.hiring is None  # far sentence in a brief: never accepted


def test_tie_back_does_not_resurrect_the_anthropic_sentence():
    # Even in a single-topic article, a bare noun about a person is still not a hiring plan.
    body = _far("Acme", "Le financement intervient après son recrutement à temps plein par "
                        "Anthropic.")
    assert extract_funding("Acme lève 7 M€", body).hiring is None


def test_funds_financing_recruitments_is_a_plan():
    result = extract_funding("Fluencify boucle un tour de 3,7 M€",
                             "Fluencify boucle un tour de 3,7 M€. Les fonds financeront des "
                             "recrutements à Stockholm.")
    assert result.hiring == "financeront des recrutements"


def test_english_hiring_requires_a_verb():
    assert extract_funding("Acme raises $5M and plans to hire 30 engineers", "").hiring
    assert extract_funding("Acme raises $5M; its hiring of a CFO was praised", "").hiring is None


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

def test_is_brief():
    assert is_brief(BRIEF_TITLE)
    assert not is_brief("Acme lève 5 M€ pour son expansion")


def test_brief_takes_every_field_from_the_company_paragraph_only():
    result = extract_funding(BRIEF_TITLE, BRIEF_BODY)
    assert result.amount == 4.3e6
    assert result.round == "seed"  # from the Jaipur paragraph, merged with its heading
    assert result.investors == ("EquityPitcher Ventures", "High-Tech Gründerfonds")
    assert result.country == "Switzerland"


def test_brief_never_borrows_round_or_hiring_from_another_paragraph():
    body = "\n".join([
        "Acme lève 2 millions d’euros pour son expansion.",
        "La startup Beta boucle une série B. Beta va recruter 50 ingénieurs.",
    ])
    result = extract_funding("Acme lève 2 M€ / Beta change de CEO", body)
    assert result.company == "Acme"
    assert result.round is None
    assert result.hiring is None


def test_non_brief_keeps_article_wide_round():
    body = "Acme lève 2 millions d’euros.\nIl s’agit d’une série A."
    assert extract_funding("Acme lève 2 M€", body).round == "series a"


def test_split_paragraphs_keeps_lines_apart():
    assert split_paragraphs("A un. B deux.\n\nC trois.") == [["A un.", "B deux."], ["C trois."]]


# ---------------------------------------------------------------------------
# Country (explicit only)
# ---------------------------------------------------------------------------

def test_country_from_company_nationality():
    assert extract_funding("La startup britannique Acme lève 5 M€", "").country == "United Kingdom"
    assert extract_funding("La pépite lyonnaise Acme lève 5 M€", "").country == "France"
    assert extract_funding("London-based Acme raises £5m", "").country == "United Kingdom"


def test_country_from_explicit_base():
    assert extract_funding("Acme, basée à Lyon, lève 5 M€", "").country == "France"


def test_country_unknown_stays_none():
    result = extract_funding("Acme lève 5 M€ auprès du fonds américain Accel", "")
    assert result.country is None  # "américain" qualifies the investor, not the company
    assert "country" not in result.evidence
