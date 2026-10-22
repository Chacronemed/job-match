"""The part of a description that says what the candidate must bring: the "Profil",
"Compétences", "Savoir-faire"… sections, when the offer names them.

The headings mirror the dashboard's layout (assets/description.js): a short line, with or
without a trailing colon, or the heading followed by its text on the same line
("Profil : Bac+5…"). A section runs to the next recognised heading of any kind. No heading,
no profile text: the scorer then weighs every skill the same, as before.
"""
from __future__ import annotations

import re

from job_match.normalization.text import normalize_text

# Folded (normalize_text) headings that open the candidate's side of the offer.
PROFILE = re.compile(
    r"^(?:(?:votre|ton|le|du) )?profil(?: (?:recherche|souhaite|attendu|requis|candidat))?"
    r"|^(?:les |vos |tes )?competences"
    r"(?: (?:requises|techniques|attendues|recherchees|cles|souhaitees))?"
    r"|^savoir (?:faire|etre)|^qualites(?: requises)?|^pre ?requis|^(?:les )?exigences"
    r"|^ce que (?:nous recherchons|l on attend de (?:vous|toi))"
    r"|^vous (?:etes|avez|possedez|maitrisez)"
    r"|^experience(?:s)? (?:et|&) competences|^formation(?: et experience)?$"
)
# Every other usual heading: it closes a profile section.
OTHER = re.compile(
    r"^(?:(?:vos|les|tes) )?missions?(?: principales)?|^(?:le |votre )?poste(?: propose)?"
    r"|^description(?: du poste)?|^descriptif(?: du poste)?|^(?:vos |tes )?responsabilites"
    r"|^(?:les )?avantages|^(?:ce que )?nous (?:vous )?(?:offrons|proposons)|^pourquoi"
    r"|^l entreprise|^(?:notre |la )?(?:entreprise|societe)|^qui sommes nous|^a propos"
    r"|^conditions|^informations complementaires|^(?:le )?process(?:us)? de recrutement"
    r"|^remuneration|^salaire|^contexte|^environnement technique"
)
_INLINE = re.compile(r"^([^:]{3,40}?)\s*:\s+(\S.*)$")
MAX_HEADING = 60


def _heading(line: str) -> str | None:
    """'profile', 'other' or None for one line (its own text, colon optional)."""
    bare = line.strip().rstrip(":").strip()
    if not bare or len(bare) > MAX_HEADING or bare[0] in "-•·*–—✓▪►":
        return None
    folded = normalize_text(bare)
    if PROFILE.match(folded) and len(folded.split()) <= 6:
        return "profile"
    if OTHER.match(folded) and len(folded.split()) <= 6:
        return "other"
    return None


def profile_text(description: str) -> str:
    """The text of the description's profile / skills sections, joined; "" when none."""
    out: list[str] = []
    inside = False
    for raw in (description or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # "Compétences : Python, Ansible" is a heading and its text: the inline branch below.
        kind = None if re.search(r":\s*\S", line) else _heading(line)
        rest = None
        if kind is None and (m := _INLINE.match(line)):
            kind = _heading(m.group(1))
            rest = m.group(2) if kind else None
        if kind:
            inside = kind == "profile"
            if inside and rest:
                out.append(rest)
            continue
        if inside:
            out.append(line)
    return "\n".join(out)
