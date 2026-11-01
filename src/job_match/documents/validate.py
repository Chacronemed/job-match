"""What the master CV must satisfy before it leaves the machine.

- `skills` are canonical names (skill vocabulary, alias keys, profile skills);
- no forbidden phrase (settings.yaml `documents.forbidden_phrases`), accent- and
  case-insensitive, anywhere in the text;
- no contact detail inside the master: an email, a phone number, a URL or the contact's
  names belong to contact.yaml only, so they never reach the model;
- ISO `YYYY-MM` dates, an end after its start, unique bullet and section IDs.
Returns readable messages, never raises on content: the CLI prints the count.
"""
from __future__ import annotations

import re

from job_match.config.schema import DocumentsConfig
from job_match.documents.master import Contact, Master
from job_match.normalization.skills import canonical_skill
from job_match.normalization.text import normalize_text

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# An international number (+33 7 62 …) or a French national one (07 62 01 54 08); a CVE id
# or a year never matches.
_PHONE = re.compile(r"\+\d{1,3}[ .-]?\d(?:[ .-]?\d){7,}|(?<!\d)0[1-9](?:[ .-]?\d{2}){4}(?!\d)")
_URL = re.compile(r"https?://|www\.|linkedin\.com/|github\.com/", re.I)


def validate_master(
    master: Master,
    contact: Contact | None,
    config: DocumentsConfig,
    vocabulary: tuple[str, ...] | list[str],
    aliases: dict[str, list[str]],
    profile_skills: tuple[str, ...] | list[str] = (),
) -> list[str]:
    errors: list[str] = []
    allowed = {s.lower() for s in (*vocabulary, *aliases, *profile_skills)}
    tools = {" ".join(t.lower().split()) for b in master.bullets() for t in b.tools}
    ids: set[str] = set()
    for skill in master.skills:
        if skill.id in ids:
            errors.append(f"skills: duplicate id {skill.id!r}")
        ids.add(skill.id)
        if canonical_skill(skill.id, aliases, allowed) is None and skill.id not in tools:
            errors.append(
                f"skills: {skill.id!r} is neither a canonical skill (vocabulary, aliases, "
                "profile) nor a tool cited by a bullet"
            )
    if not _DAY.match(master.available_from):
        errors.append("available_from must be YYYY-MM-DD")
    for b in master.bullets():
        if any(t.lower() == "" for t in b.tools):
            errors.append(f"{b.id}: empty tool name")

    phrases = [normalize_text(p) for p in config.forbidden_phrases if normalize_text(p)]
    for label, text in master.texts():
        folded = normalize_text(text)
        for phrase in phrases:
            if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", folded):
                errors.append(f"{label}: forbidden phrase {phrase!r}")
        if _EMAIL.search(text):
            errors.append(f"{label}: contains an email address (contact.yaml only)")
        if _PHONE.search(text):
            errors.append(f"{label}: contains a phone number (contact.yaml only)")
        if _URL.search(text):
            errors.append(f"{label}: contains a URL or a profile link (contact.yaml only)")
        if contact is not None:
            for name in (contact.first_name, contact.last_name):
                pattern = r"(?<!\w)" + re.escape(normalize_text(name)) + r"(?!\w)"
                if name and re.search(pattern, folded):
                    errors.append(f"{label}: contains the candidate's name (contact.yaml only)")
                    break

    seen: set[str] = set()
    ids = [e.id for e in master.experiences] + [p.id for p in master.projects]
    for sid in ids + [b.id for b in master.bullets()]:
        if sid in seen:
            errors.append(f"duplicate id {sid!r}")
        seen.add(sid)
    for e in master.experiences:
        errors += _dates(e.id, e.start, e.end)
    for i, ed in enumerate(master.education):
        errors += _dates(f"education[{i}]", ed.start, ed.end)
    return errors


def _dates(label: str, start: str, end: str | None) -> list[str]:
    out = []
    if not _MONTH.match(start):
        out.append(f"{label}: start must be YYYY-MM")
    if end is not None and not _MONTH.match(end):
        out.append(f"{label}: end must be YYYY-MM or null")
    elif end is not None and _MONTH.match(start) and end < start:
        out.append(f"{label}: end before start")
    return out
