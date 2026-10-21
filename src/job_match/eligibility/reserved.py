"""Offers reserved for disabled workers (RQTH / BOETH holders).

Only restrictive wording counts: "Poste réservé aux travailleurs handicapés", "RQTH
obligatoire", "titulaire d'une RQTH". Inclusive wording is common and must never reject:
"nos postes sont ouverts aux personnes en situation de handicap", "handi-accueillant",
the Talents Handicap boilerplate. None of it matches a pattern below; the tests pin that down.

Each sentence is tested on its own, so "Poste réservé aux alternants." never pairs with a
handicap mention in the next sentence.
"""
import re

from job_match.normalization.skills import sentences

_DISABLED = r"(?:handicap[ée]e?s?|en situation de handicap)"
# "n'est pas réservé", "non réservé": the opposite statement.
_NOT_NEGATED = r"(?<!pas )(?<!non )(?<!non-)"
_RESERVED = rf"{_NOT_NEGATED}r[ée]serv[ée]e?s?"

_RESTRICTIVE = [
    re.compile(rf"{_RESERVED} aux (?:personnes|travailleu(?:rs|ses)) {_DISABLED}", re.I),
    re.compile(r"\bRQTH (?:est )?(?:obligatoire|exig[ée]e|requise)\b", re.I),
    re.compile(r"\btitulaires? (?:de la|d['’]une) RQTH\b", re.I),
    re.compile(rf"\bpostes? {_RESERVED}\b.*\b(?:RQTH|handicap)", re.I),
]
# "uniquement aux bénéficiaires" alone is too wide ("… du RSA" is another scheme): it counts
# only when the same sentence is about disability.
_ONLY_BENEFICIARIES = re.compile(r"\buniquement (?:aux|pour les) b[ée]n[ée]ficiaires\b", re.I)
_DISABILITY_CONTEXT = re.compile(
    r"handicap|\bRQTH\b|\bB?OETH\b|obligation d['’]emploi", re.I
)


def rqth_reserved(text: str) -> str | None:
    """The first sentence reserving the offer for RQTH / BOETH holders, else None."""
    for sentence in sentences(text or ""):
        if any(p.search(sentence) for p in _RESTRICTIVE):
            return sentence
        if _ONLY_BENEFICIARIES.search(sentence) and _DISABILITY_CONTEXT.search(sentence):
            return sentence
    return None
