"""Offers reserved for disabled workers (RQTH / BOETH holders).

Only restrictive wording counts: "Poste réservé aux travailleurs handicapés", "RQTH
obligatoire", "titulaire d'une RQTH". Inclusive wording is common and must never reject:
"nos postes sont ouverts aux personnes en situation de handicap", "handi-accueillant". None
of it matches a pattern below; the tests pin that down.

A recruiter whose job is placing RQTH candidates (`settings.eligibility.rqth_recruiters`,
e.g. Talents Handicap) is the other case: its offers never say "réservé", so it is matched by
name, and the note keeps the end client the same job may exist at directly.

Each sentence is tested on its own, so "Poste réservé aux alternants." never pairs with a
handicap mention in the next sentence.
"""
import re

from job_match.normalization.skills import contains_term, sentences
from job_match.normalization.text import normalize_text

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


# A specialised recruiter's own boilerplate: "Talents Handicap accompagne … dans leurs
# recrutements de collaborateurs en situation de handicap". The name alone is not enough
# (an employer may cite the forum it attends); the recruiting sentence is.
_PLACES_DISABLED = re.compile(r"accompagn\w*.*\brecrut\w*.*(?:handicap|\bRQTH\b)", re.I)

# The company the job is really at, when the recruiter names it.
_END_CLIENT = [
    re.compile(r"\bL['’]entreprise (?P<client>[^,;:]{2,60}?) (?:recherche|recrute)\b"),
    re.compile(r"\b[Pp]our le compte de (?:notre client |son client )?"
               r"(?P<client>[A-Z][^,;:]{1,59}?)(?=[,;:]| recherche| recrute|$)"),
]


def rqth_recruiter(company: str | None, text: str, names: list[str]) -> str | None:
    """The listed RQTH-specialised recruiter behind this offer, else None.

    Matched on the company name (accent- and case-insensitive whole term, so "Forums Talents
    Handicap" is Talents Handicap) or on a sentence where the recruiter says it places
    disabled candidates.
    """
    folded_company = normalize_text(company or "")
    for name in names:
        folded = normalize_text(name)
        if folded and folded_company and contains_term(folded_company, folded):
            return name
    for sentence in sentences(text or ""):
        if not _PLACES_DISABLED.search(sentence):
            continue
        for name in names:
            if name and contains_term(sentence, name):
                return name
    return None


def end_client(text: str) -> str | None:
    """The end client a recruiter names ("L'entreprise X recherche…"), else None."""
    for sentence in sentences(text or ""):
        for pattern in _END_CLIENT:
            m = pattern.search(sentence)
            if m:
                return m.group("client").strip()
    return None


def recruiter_note(recruiter: str, client: str | None) -> str:
    note = f"publié par {recruiter} (recruteur spécialisé RQTH)"
    if client:
        note += f" — le poste peut exister en direct chez {client}"
    return note
