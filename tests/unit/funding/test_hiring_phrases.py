"""Hiring phrase patterns: verb/plan required (real sentences from 2026-10-05 articles)."""
import pytest

from job_match.funding.extractor import _hiring_in


@pytest.mark.parametrize("sentence,phrase", [
    ("Wealthcome prévoit de poursuivre ses recrutements pour accompagner cette montée.",
     "poursuivre ses recrutements"),
    ("La startup compte 50 collaborateurs, et prévoit de doubler de nouveau ses effectifs.",
     "doubler de nouveau ses effectifs"),
    ("Les capitaux doivent soutenir les recrutements et le développement des capacités.",
     "soutenir les recrutements"),
    ("Les 35 M€ financent aussi le recrutement d’équipes opérationnelles aux États-Unis.",
     "financent aussi le recrutement d’équipes"),
    ("Le financement soutiendra ses recrutements et son expansion européenne.",
     "soutiendra ses recrutements"),
    ("Une trentaine de recrutements sont annoncés dans les prochains mois.",
     "Une trentaine de recrutements"),
])
def test_plan_phrases_are_hiring(sentence, phrase):
    assert _hiring_in(sentence) == phrase


@pytest.mark.parametrize("sentence", [
    "Son recrutement à temps plein par Anthropic avait suscité des critiques.",
    "Le gain peut financer une réduction d’erreurs ou un recrutement évité.",
    "Dans ses annonces de recrutement, elle se présente comme une alternative.",
    "Arlequin revendique une trentaine de collaborateurs.",
    "The hiring of a new CFO was announced.",
])
def test_bare_nouns_and_headcount_are_not_hiring(sentence):
    assert _hiring_in(sentence) is None
