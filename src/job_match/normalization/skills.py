"""Shared term matching for skills (scorer + relevance gate) and title keywords."""
import re

from job_match.normalization.text import normalize_text


def skill_forms(name: str, aliases: dict[str, list[str]]) -> list[str]:
    """Canonical skill name plus its aliases, lowercased."""
    canonical = name.lower()
    return [canonical] + [a.lower() for a in aliases.get(canonical, [])]


def find_term(text: str, term: str) -> re.Match[str] | None:
    """Whole-term, case-insensitive match: `ci/cd` works, `java` never matches `javascript`."""
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE)


def contains_term(text: str, term: str) -> bool:
    return find_term(text, term) is not None


def find_skill(text: str, name: str, aliases: dict[str, list[str]]) -> re.Match[str] | None:
    """Earliest match of the skill or one of its aliases, None when absent."""
    found = [m for form in skill_forms(name, aliases) if (m := find_term(text, form))]
    return min(found, key=lambda m: m.start()) if found else None


def matches_skill(text: str, name: str, aliases: dict[str, list[str]]) -> bool:
    return find_skill(text, name, aliases) is not None


SNIPPET_MAX = 160
# Sentence or bullet boundaries a snippet never crosses.
# A full stop only ends a sentence before a space, so "node.js" and "asp.net" stay whole.
_BOUNDARY_RE = re.compile(r"[.!?;](?=\s|$)|[\u2022\n\r]")


def snippet(text: str, start: int, end: int, max_len: int = SNIPPET_MAX) -> str:
    """The sentence around text[start:end], whitespace collapsed, at most `max_len` chars.

    A longer sentence is cut to a window centred on the match, with "…" on the cut sides.
    """
    left = max((m.end() for m in _BOUNDARY_RE.finditer(text, 0, start)), default=0)
    right_m = _BOUNDARY_RE.search(text, end)
    right = right_m.start() if right_m else len(text)
    if right - left > max_len:
        max_len -= 2  # room for the two ellipses
        half = max(0, (max_len - (end - start)) // 2)
        lo = max(left, start - half)
        hi = min(right, lo + max_len)
        lo = max(left, hi - max_len)
        out = text[lo:hi]
        prefix = "…" if lo > left else ""
        suffix = "…" if hi < right else ""
    else:
        out, prefix, suffix = text[left:right], "", ""
    # A bullet's own marker ("- ", "* ") is layout, not part of the sentence.
    body = " ".join(out.split()).lstrip("-*·–— ")
    return f"{prefix}{body}{suffix}" if body else ""


def title_term(title: str, terms: list[str]) -> str | None:
    """First term present in the title as a whole word, accent- and case-insensitive.

    Whole-word, unlike `title_keyword`: ".net" normalizes to "net" and must not match
    "network", and "dev" must not match "devops". Use this when a false positive costs
    more than a miss.
    """
    folded = normalize_text(title)
    for term in terms:
        t = normalize_text(term)
        if t and contains_term(folded, t):
            return term
    return None


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
