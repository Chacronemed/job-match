"""Table-driven tests for the rule-based funding extractor (FR + EN).

Every case is a realistic headline or mini-article. Negatives cover revenue, valuation,
idioms ("lève le voile"), past funding mentioned in passing, VC fund closes and amounts
without a unit. Unknown must stay None: a wrong value is worse than no value.
"""
from pathlib import Path

import pytest

from job_match.funding.extractor import (
    MAX_EVIDENCE_CHARS,
    FundingExtraction,
    extract_funding,
    format_amount,
    split_sentences,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

P1 = (
    "La startup parisienne Acme annonce aujourd'hui un tour de table de 10 millions d'euros en "
    "série A, mené par le fonds Exemple Capital avec la participation de ses investisseurs "
    "historiques."
)
P2 = (
    "Avec cette levée, Acme prévoit de doubler ses effectifs d'ici douze mois et de recruter une "
    "trentaine de personnes, principalement des ingénieurs logiciel et des profils SRE basés à "
    "Paris et à Nantes."
)
ROUNDUP_TITLE = "French Tech : l'IA capte près de 90 % des 59 millions d'euros levés cette semaine"
ELEVENLABS_TITLE = "ELEVENLABS valorisée 19,4 milliards d'euros : la bataille des agents vocaux"
ELEVENLABS_BODY = (
    "Valorisée environ 19,4 milliards d'euros à l'occasion d'une opération de liquidité de "
    "264 millions d'euros, ElevenLabs accélère sa mue."
)

# (id, title, body, expected fields)
CASES = [
    # --- FR positives ---------------------------------------------------------------
    ("fr_simple", "Acme lève 10 millions d'euros pour sa plateforme DevOps", "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR", round=None,
          investors=None, hiring=None)),
    ("fr_fixture_para", P1, "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR", round="series a",
          investors=("Exemple Capital", "investisseurs historiques"))),
    ("fr_bullet_leve", "- InBolt lève 11 millions d'euros pour accélérer le déploiement.", "",
     dict(is_funding=True, company="InBolt", amount=1.1e7, currency="EUR")),
    ("fr_bullet_boucle", "- Mallow boucle un tour de 11 millions d'euros pour sa plateforme.", "",
     dict(is_funding=True, company="Mallow", amount=1.1e7, currency="EUR")),
    ("fr_milliard_decimal", "La fintech Qonto boucle une levée de fonds de 1,5 milliard d'euros.",
     "", dict(is_funding=True, company="Qonto", amount=1.5e9, currency="EUR")),
    ("fr_seed_aupres", "Back Market lève 10 M€ en seed auprès de Kima Ventures et Bpifrance.", "",
     dict(is_funding=True, company="Back Market", amount=1e7, currency="EUR", round="seed",
          investors=("Kima Ventures", "Bpifrance"))),
    ("fr_thousands_sep", "La pépite nantaise Alpha a levé 500 000 euros auprès de business angels.",
     "", dict(is_funding=True, company="Alpha", amount=5e5, currency="EUR",
              investors=("business angels",))),
    ("fr_k_preseed", "Beta sécurise un financement de 300 k€ en pré-amorçage.", "",
     dict(is_funding=True, company="Beta", amount=3e5, currency="EUR", round="pre-seed")),
    ("fr_md_series_c", "Gamma annonce une levée de fonds de 2 Md€ en série C.", "",
     dict(is_funding=True, company="Gamma", amount=2e9, currency="EUR", round="series c")),
    ("fr_usd_symbol", "Delta lève 5 M$ auprès d'Index Ventures.", "",
     dict(is_funding=True, company="Delta", amount=5e6, currency="USD",
          investors=("Index Ventures",))),
    ("fr_dollars_word", "Epsilon lève 20 millions de dollars en série B, un tour dirigé par Accel.",
     "", dict(is_funding=True, company="Epsilon", amount=2e7, currency="USD", round="series b",
              investors=("Accel",))),
    ("fr_alnum_name", "H2 Pulse lève 12 M€.", "",
     dict(is_funding=True, company="H2 Pulse", amount=1.2e7, currency="EUR")),
    ("fr_allcaps_name", "ELEVENLABS lève 180 millions de dollars en série C", "",
     dict(is_funding=True, company="ELEVENLABS", amount=1.8e8, currency="USD",
          round="series c")),
    ("fr_appositive", "Acme, la fintech lyonnaise, lève 4 M€.", "",
     dict(is_funding=True, company="Acme", amount=4e6, currency="EUR")),
    ("fr_no_amount", "Acme lève des fonds auprès de Bpifrance.", "",
     dict(is_funding=True, company="Acme", amount=None, currency=None,
          investors=("Bpifrance",))),
    ("fr_written_number", "Acme a bouclé un tour de table de dix millions d'euros.", "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR")),
    ("fr_full_article", "Acme lève 10 millions d'euros pour sa plateforme DevOps", P1 + "\n" + P2,
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR", round="series a",
          hiring="doubler ses effectifs", location="Paris")),
    ("fr_hiring_count", "Zeta vient de lever 3 millions d'euros.",
     "L'entreprise compte réaliser 25 recrutements d'ici 2027.",
     dict(is_funding=True, company="Zeta", amount=3e6, currency="EUR",
          hiring="25 recrutements")),
    ("fr_hiring_in_title", "Acme lève 10 M€ pour recruter 50 ingénieurs et ouvrir un bureau.", "",
     dict(is_funding=True, company="Acme", amount=1e7, hiring="recruter 50 ingénieurs")),
    # --- EN positives ---------------------------------------------------------------
    ("en_seed_led_by", "Acme raises $5M seed round led by Index Ventures", "",
     dict(is_funding=True, company="Acme", amount=5e6, currency="USD", round="seed",
          investors=("Index Ventures",))),
    ("en_gbp_from",
     "London-based Beta has raised £2.5m in pre-seed funding from Seedcamp and angel investors.",
     "", dict(is_funding=True, company="Beta", amount=2.5e6, currency="GBP", round="pre-seed",
              investors=("Seedcamp", "angel investors"))),
    ("en_participation",
     "Gamma secures $50 million Series B led by Sequoia, with participation from Accel and "
     "existing investors.", "",
     dict(is_funding=True, company="Gamma", amount=5e7, currency="USD", round="series b",
          investors=("Sequoia", "Accel", "existing investors"))),
    ("en_eur_symbol_first", "Delta closes €12m Series A to expand across Europe.", "",
     dict(is_funding=True, company="Delta", amount=1.2e7, currency="EUR", round="series a")),
    ("en_billion_hiring",
     "Epsilon lands $1.2 billion in new funding; the company plans to double its headcount "
     "by 2027.", "",
     dict(is_funding=True, company="Epsilon", amount=1.2e9, currency="USD",
          hiring="double its headcount")),
    ("en_no_amount_hiring", "Zeta raises funding to grow its team", "",
     dict(is_funding=True, company="Zeta", amount=None, hiring="grow its team")),
    # --- negatives ------------------------------------------------------------------
    ("neg_revenue", "Acme affiche un chiffre d'affaires de 10 M€ et vise la rentabilité.", "",
     dict(is_funding=False)),
    ("neg_valuation_liquidity", ELEVENLABS_TITLE, ELEVENLABS_BODY, dict(is_funding=False)),
    ("neg_leve_le_voile", "Acme lève le voile sur sa nouvelle plateforme.", "",
     dict(is_funding=False)),
    ("neg_past_fr", "Acme, qui avait levé 5 M€ en 2022, lance une nouvelle offre.", "",
     dict(is_funding=False)),
    ("neg_past_en", "After raising $3M in 2021, Beta is now profitable.", "",
     dict(is_funding=False)),
    ("neg_raises_the_bar", "Acme raises the bar for cloud security.", "", dict(is_funding=False)),
    ("neg_market_size", "Le marché de la cybersécurité pèse 10 milliards d'euros.", "",
     dict(is_funding=False)),
    ("neg_vc_fund", "Exemple Capital lève 200 M€ pour son deuxième fonds.", "",
     dict(is_funding=False)),
    ("neg_below_sanity", "Acme lève 500 euros", "", dict(is_funding=False)),
    ("neg_roundup_title_alone", ROUNDUP_TITLE, "", dict(is_funding=False)),
    ("neg_past_with_date_fr",
     "Après avoir séduit Doctolib, Pivot a levé 40 millions de dollars en mai 2026.", "",
     dict(is_funding=False)),
    ("neg_past_with_date_en", "Beta raised $3M in March 2025 and is now profitable.", "",
     dict(is_funding=False)),
    ("neg_since_round_last_month",
     "La société était valorisée à 11 milliards de dollars depuis un tour de table en série D "
     "de 500 millions de dollars en février dernier.", "", dict(is_funding=False)),
    ("neg_listicle_past_then_present",
     "5 startups à suivre",
     "Pivot a levé 40 millions de dollars en mai 2026.L'entreprise mise sur l'IA agentique.",
     dict(is_funding=False)),
    # --- mixed / tricky -------------------------------------------------------------
    ("mix_revenue_then_raise",
     "Acme, qui réalise 2 M€ de chiffre d'affaires, lève 10 M€ en série A.", "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR", round="series a")),
    ("mix_total_to_date", "Acme lève 10 M€, portant le total levé à 25 M€ depuis sa création.", "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR")),
    ("mix_no_company", "La startup lève 3 M€ pour accélérer.", "",
     dict(is_funding=True, company=None, amount=3e6, currency="EUR")),
    ("mix_recruiting_platform", "Plateforme de recrutement, Acme lève 2 M€.", "",
     dict(is_funding=True, company="Acme", amount=2e6, currency="EUR", hiring=None)),
    ("mix_parenthesis_usd", "Acme lève 10 M€ (11 M$) en série A après 2 M€ en seed.", "",
     dict(is_funding=True, company="Acme", amount=1e7, currency="EUR", round="series a")),
    ("mix_debt_equity", "Acme lève 2 M€ en dette auprès de Bpifrance et 8 M€ en equity.", "",
     dict(is_funding=True, company="Acme")),
    ("mix_headcount_is_not_hiring", "Joe AI lève 2 millions d'euros.",
     "L'équipe compte 10 collaborateurs.",
     dict(is_funding=True, company="Joe AI", amount=2e6, hiring=None)),
    ("mix_aux_cotes_de",
     "Inbolt lève 11 millions d'euros dans un tour mené par Shift4Good aux côtés de Bridges "
     "Climate Transition Partners et Ora Global.", "",
     dict(is_funding=True, company="Inbolt", amount=1.1e7,
          investors=("Shift4Good", "Bridges Climate Transition Partners", "Ora Global"))),
    ("mix_investor_descriptor_trimmed",
     "Joe AI lève 2 millions d'euros auprès de Xplore, branche de capital-innovation "
     "d'Épopée Gestion.", "",
     dict(is_funding=True, company="Joe AI", investors=("Xplore", "Épopée Gestion"))),
    ("mix_recruiting_phrase_is_hiring", "Inbolt lève 11 millions d'euros.",
     "L'essentiel des fonds servira à recruter des profils commerciaux et d'ingénierie.",
     dict(is_funding=True, hiring="recruter des profils")),
]


@pytest.mark.parametrize("case_id,title,body,expected", CASES, ids=[c[0] for c in CASES])
def test_extraction_matrix(case_id, title, body, expected):
    result = extract_funding(title, body)
    for field_name, want in expected.items():
        got = getattr(result, field_name)
        assert got == want, f"{case_id}: {field_name} got {got!r} want {want!r}\n{result}"


def test_roundup_uses_first_deal_sentence_not_summary_line():
    body = (FIXTURES / "article_roundup.txt").read_text(encoding="utf-8")
    result = extract_funding(ROUNDUP_TITLE, body)

    assert result.is_funding
    assert result.company == "InBolt"
    assert result.amount == 1.1e7  # not the 52,8 M€ summary total
    assert "InBolt" in result.evidence["amount"]


def test_evidence_keys_only_for_known_fields_and_bounded():
    result = extract_funding("Acme lève des fonds auprès de Bpifrance.", "")
    assert set(result.evidence) == {"funding", "company", "investors"}
    assert all(len(v) <= MAX_EVIDENCE_CHARS for v in result.evidence.values())

    long_title = "Acme lève 10 M€ " + "pour accélérer son développement " * 20
    long_result = extract_funding(long_title, "")
    assert len(long_result.evidence["amount"]) == MAX_EVIDENCE_CHARS


def test_non_funding_result_is_empty():
    assert extract_funding("Acme recrute 50 personnes", "") == FundingExtraction(is_funding=False)


def test_empty_inputs():
    assert extract_funding("", "") == FundingExtraction(is_funding=False)
    assert extract_funding(None, None) == FundingExtraction(is_funding=False)  # type: ignore


# ---------------------------------------------------------------------------
# split_sentences / format_amount
# ---------------------------------------------------------------------------

def test_split_sentences_handles_abbreviations_decimals_and_bullets():
    text = "M. Dupont lève 1,5 M€. Il a 19.4 ans d'âge.\n- bullet one\n- bullet two\n\n"
    assert split_sentences(text) == [
        "M. Dupont lève 1,5 M€.",
        "Il a 19.4 ans d'âge.",
        "bullet one",
        "bullet two",
    ]


def test_split_sentences_without_space_after_period():
    assert split_sentences("Pivot a levé 40 M$ en mai 2026.L'entreprise mise sur l'IA.") == [
        "Pivot a levé 40 M$ en mai 2026.",
        "L'entreprise mise sur l'IA.",
    ]
    assert split_sentences("Il a 19.4 ans et pèse 1.5 M€.") == ["Il a 19.4 ans et pèse 1.5 M€."]


def test_split_sentences_normalizes_nbsp_and_whitespace():
    assert split_sentences("10 M€   levés.  Fin.") == ["10 M€ levés.", "Fin."]


@pytest.mark.parametrize(
    "amount,currency,expected",
    [
        (1e7, "EUR", "10 M€"),
        (1.5e9, "EUR", "1,5 Md€"),
        (3e5, "EUR", "300 k€"),
        (2.5e6, "GBP", "2,5 M£"),
        (5e6, "USD", "$5M"),
        (1.2e9, "USD", "$1.2B"),
        (None, "EUR", None),
    ],
)
def test_format_amount(amount, currency, expected):
    assert format_amount(amount, currency) == expected
