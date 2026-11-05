"""What a form field asks, from its label, name, id, placeholder and autocomplete (ADR 0023).

The words live in `config/apply_questions.yaml` and the fixed answers in private/apply.yaml.
Order matters and is fixed here: a sensitive question or a consent box is never filled,
whatever else it mentions; a salary field is decided by the salary rule alone.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from job_match.apply.config import ApplyConfig
from job_match.config.schema import ConfigError

# Kinds, in the order they are tried.
NEVER_FILL = ("sensitive", "consent")
IDENTITY = ("first_name", "last_name", "full_name", "email", "phone", "linkedin", "github")
FILES = ("resume", "cover_letter")
KIT = ("why_company", "motivation", "availability", "notice", "mobility")
CATEGORIES = (*NEVER_FILL, "salary", *IDENTITY, *FILES, *KIT)
# A bare "name" / "nom" is my name only when it is the whole label or the field's name: never
# in "Company name" or "Nom de l'entreprise".
WHOLE_LABEL_ONLY = ("full_name",)
TEXT_TYPES = ("text", "email", "tel", "url", "number", "search", "textarea", "")


def fold(text: str) -> str:
    """Accent-folded, lowercased, punctuation to spaces, single spaces."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^\w\s]|_", " ", t)
    return " ".join(t.split())


def _has(haystack: str, phrase: str) -> bool:
    return f" {phrase} " in f" {haystack} "


@dataclass(frozen=True)
class Field:
    """A form control as the page scan reports it. `options`: a select's or a radio group's
    option labels. `ref`: the scan's handle on the page (data-jm-field)."""
    ref: str
    tag: str  # input | textarea | select | radio
    type: str  # the input type, "" for textarea / select
    label: str
    name: str = ""
    id: str = ""
    placeholder: str = ""
    autocomplete: str = ""
    required: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Kind:
    category: str  # a CATEGORIES name, "fixed", "password" or "unknown"
    fixed_index: int | None = None  # the apply.yaml answer, for "fixed"


class Questions:
    def __init__(self, words: dict[str, list[str]],
                 equivalents: list[list[str]] | tuple = ()):
        missing = [c for c in CATEGORIES if c not in words]
        if missing:
            raise ConfigError(f"apply_questions.yaml: missing {', '.join(missing)}")
        self.words = {c: [fold(w) for w in words[c] if fold(w)] for c in CATEGORIES}
        # Groups of option texts that say the same thing in French and English.
        self.equivalents = [tuple(fold(w) for w in g if fold(w)) for g in equivalents]

    def option_forms(self, *answers: str) -> list[str]:
        """Every folded text an option may read for these answers: the answers themselves,
        then the members of each equivalence group one of them belongs to."""
        out: list[str] = []
        for a in answers:
            f = fold(a)
            if f and f not in out:
                out.append(f)
        for f in list(out):
            for group in self.equivalents:
                if f in group:
                    out += [w for w in group if w not in out]
        return out

    def classify(self, field: Field, apply: ApplyConfig) -> Kind:
        if field.type == "password":
            return Kind("password")
        label = fold(field.label)
        attrs = [fold(a) for a in (field.name, field.id, field.autocomplete) if a]
        text = " ".join([label, fold(field.placeholder), *attrs])

        def hit(category: str) -> bool:
            if category in WHOLE_LABEL_ONLY:
                return any(w == label or w in attrs for w in self.words[category])
            return any(_has(text, w) for w in self.words[category])

        if hit("sensitive"):
            return Kind("sensitive")
        if field.type == "checkbox":
            # Never ticked: a consent box, or a question I answer myself.
            return Kind("consent" if hit("consent") else "unknown")
        if hit("salary"):
            return Kind("salary")
        for i, answer in enumerate(apply.reponses_fixes):
            if any(_has(text, fold(w)) for w in answer.match):
                return Kind("fixed", i)
        if field.type == "file":
            for c in FILES:
                if hit(c):
                    return Kind(c)
            return Kind("unknown")
        if field.tag != "radio" and field.type not in TEXT_TYPES and field.tag != "select":
            return Kind("unknown")
        for c in (*IDENTITY, "cover_letter", *KIT):
            if c == "cover_letter" and field.tag != "textarea":
                continue
            if hit(c):
                return Kind(c)
        return Kind("unknown")


def load_questions(path: Path) -> Questions:
    if not path.exists():
        raise ConfigError(f"File not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: must be a mapping")
    equivalents = raw.pop("option_equivalents", None) or []
    if not isinstance(equivalents, list) or not all(
        isinstance(g, list) and len(g) >= 2 and all(isinstance(w, str) for w in g)
        for g in equivalents
    ):
        raise ConfigError(f"{path}: option_equivalents must be a list of lists of 2+ strings")
    if not all(isinstance(v, list) and all(isinstance(w, str) for w in v) for v in raw.values()):
        raise ConfigError(f"{path}: every category must be a list of strings")
    return Questions(raw, equivalents)
