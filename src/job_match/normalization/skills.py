"""Shared term matching for skills (scorer + relevance gate) and title keywords."""
import re

from job_match.normalization.text import normalize_text


def skill_forms(name: str, aliases: dict[str, list[str]]) -> list[str]:
    """Canonical skill name plus its aliases, lowercased."""
    canonical = name.lower()
    return [canonical] + [a.lower() for a in aliases.get(canonical, [])]


def contains_term(text: str, term: str) -> bool:
    """Whole-term, case-insensitive match: `ci/cd` works, `java` never matches `javascript`."""
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) is not None


def matches_skill(text: str, name: str, aliases: dict[str, list[str]]) -> bool:
    return any(contains_term(text, form) for form in skill_forms(name, aliases))


def title_keyword(title: str, keywords: list[str]) -> str | None:
    """First keyword found at the start of a word in the title, accent- and case-insensitive.

    Prefix match on purpose: "infra" matches "Infrastructure", "système" matches "Systèmes".
    """
    folded = f" {normalize_text(title)} "
    for kw in keywords:
        k = normalize_text(kw)
        if k and re.search(r"(?<!\w)" + re.escape(k), folded):
            return kw
    return None
