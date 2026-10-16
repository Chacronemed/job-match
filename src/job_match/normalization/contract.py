"""Contract type from free text (FR + EN).

France Travail ships a clean code (`typeContrat`), so its adapter maps that directly.
Jooble and Adzuna ship free text, or nothing at all, which is why this lives here rather
than in one adapter: the mapping is shared, the field names are not.

Anything unrecognised is `UNKNOWN`, never a guess. "Full-time" is working time, not a
contract type, and deliberately does not map to CDI.
"""
import re

from job_match.domain.models import ContractType
from job_match.normalization.text import normalize_text

# Order matters: the first match wins, so the specific forms come before the generic
# ones ("contrat a duree determinee" before "contrat").
_PATTERNS: tuple[tuple[ContractType, tuple[str, ...]], ...] = (
    (ContractType.ALTERNANCE, ("alternance", "apprentissage", "apprenticeship",
                               "contrat de professionnalisation", "alternant")),
    (ContractType.STAGE, ("stage", "stagiaire", "internship", "intern")),
    (ContractType.INTERIM, ("interim", "temporary", "mission d interim", "vacataire")),
    (ContractType.FREELANCE, ("freelance", "independant", "auto entrepreneur",
                              "portage salarial", "contractor", "self employed")),
    (ContractType.CDD, ("cdd", "contrat a duree determinee", "fixed term", "fixed-term")),
    (ContractType.CDI, ("cdi", "contrat a duree indeterminee", "permanent")),
)


def parse_contract_type(*texts: str | None) -> ContractType:
    """First contract type named in the given texts, most reliable field first.

    Call it with the source's own contract field before the description, so an explicit
    field wins over a word that happens to appear in the body text.
    """
    for text in texts:
        if not text:
            continue
        normalized = normalize_text(text)
        for contract, terms in _PATTERNS:
            for term in terms:
                if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", normalized):
                    return contract
    return ContractType.UNKNOWN
