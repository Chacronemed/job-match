"""The master CV and the contact sheet, as YAML files under private/ (gitignored).

The master is the only source the generator may draw from: experiences, bullets with stable
IDs, canonical skills, education, languages, projects. It carries no contact detail: those
live in `contact.yaml`, pushed to R2 as a separate object and never sent to the model.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from job_match.config.schema import ConfigError

CONTACT_KEYS = (
    "first_name", "last_name", "title", "email", "phone", "linkedin", "github", "location",
)


@dataclass(frozen=True)
class Bullet:
    id: str
    text: str
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Experience:
    id: str
    employer: str
    title: str
    start: str
    end: str | None
    location: str
    bullets: list[Bullet]


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    bullets: list[Bullet]


@dataclass(frozen=True)
class Education:
    degree: str
    school: str
    location: str
    start: str
    end: str | None


@dataclass(frozen=True)
class Language:
    name: str
    level: str


@dataclass(frozen=True)
class Skill:
    """A catalog entry: the model answers with `id`, the template prints `label`."""

    id: str
    label: str


@dataclass(frozen=True)
class SkillGroup:
    group: str
    items: list[str]


@dataclass(frozen=True)
class Master:
    headline: str
    target: str
    available_from: str  # YYYY-MM-DD: "available immediately" once it is past
    mobility: str
    experiences: list[Experience]
    projects: list[Project]
    skills: list[Skill]
    skill_groups: list[SkillGroup]
    education: list[Education]
    certifications: list[str]
    languages: list[Language]
    extras: list[str]

    def bullets(self) -> list[Bullet]:
        out = [b for e in self.experiences for b in e.bullets]
        out += [b for p in self.projects for b in p.bullets]
        return out

    def texts(self) -> list[tuple[str, str]]:
        """Every free-text field with a label, for the phrase and PII checks."""
        out = [("headline", self.headline), ("target", self.target), ("mobility", self.mobility)]
        out += [(f"skills.{s.id}", s.label) for s in self.skills]
        for e in self.experiences:
            out += [(f"{e.id}.employer", e.employer), (f"{e.id}.title", e.title),
                    (f"{e.id}.location", e.location)]
            out += [(b.id, b.text) for b in e.bullets]
            out += [(f"{b.id}.tools", ", ".join(b.tools)) for b in e.bullets]
        for p in self.projects:
            out += [(f"{p.id}.name", p.name)]
            out += [(b.id, b.text) for b in p.bullets]
            out += [(f"{b.id}.tools", ", ".join(b.tools)) for b in p.bullets]
        out += [(f"skill_groups.{g.group}", ", ".join(g.items)) for g in self.skill_groups]
        out += [(f"education[{i}]", f"{ed.degree} {ed.school} {ed.location}")
                for i, ed in enumerate(self.education)]
        out += [(f"certifications[{i}]", c) for i, c in enumerate(self.certifications)]
        out += [(f"extras[{i}]", x) for i, x in enumerate(self.extras)]
        return out


@dataclass(frozen=True)
class Contact:
    first_name: str
    last_name: str
    title: str
    email: str
    phone: str
    linkedin: str
    github: str
    location: str


def _str(raw: dict, key: str, where: str, *, required: bool = True) -> str:
    v = raw.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ConfigError(f"{where}: missing {key}")
        return ""
    if not isinstance(v, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return v.strip()


def _str_list(raw: dict, key: str, where: str) -> list[str]:
    v = raw.get(key) or []
    if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
        raise ConfigError(f"{where}: {key} must be a list of strings")
    return [s.strip() for s in v if s.strip()]


def _bullets(raw: dict, where: str) -> list[Bullet]:
    items = raw.get("bullets") or []
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{where}: bullets must be a non-empty list")
    out = []
    for i, b in enumerate(items):
        if not isinstance(b, dict):
            raise ConfigError(f"{where}: bullets[{i}] must be a mapping")
        bid = _str(b, "id", f"{where}.bullets[{i}]")
        out.append(Bullet(id=bid, text=_str(b, "text", bid), tools=_str_list(b, "tools", bid)))
    return out


def _end(raw: dict, where: str) -> str | None:
    v = raw.get("end")
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{where}: end must be a string or null")
    return v.strip()


def parse_master(raw: object, where: str = "cv_master.yaml") -> Master:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a mapping")
    experiences = []
    for i, e in enumerate(raw.get("experiences") or []):
        if not isinstance(e, dict):
            raise ConfigError(f"{where}: experiences[{i}] must be a mapping")
        eid = _str(e, "id", f"experiences[{i}]")
        experiences.append(Experience(
            id=eid, employer=_str(e, "employer", eid), title=_str(e, "title", eid),
            start=_str(e, "start", eid), end=_end(e, eid),
            location=_str(e, "location", eid, required=False), bullets=_bullets(e, eid),
        ))
    projects = []
    for i, p in enumerate(raw.get("projects") or []):
        if not isinstance(p, dict):
            raise ConfigError(f"{where}: projects[{i}] must be a mapping")
        pid = _str(p, "id", f"projects[{i}]")
        projects.append(Project(id=pid, name=_str(p, "name", pid), bullets=_bullets(p, pid)))
    groups = []
    for i, g in enumerate(raw.get("skill_groups") or []):
        if not isinstance(g, dict):
            raise ConfigError(f"{where}: skill_groups[{i}] must be a mapping")
        groups.append(SkillGroup(group=_str(g, "group", f"skill_groups[{i}]"),
                                 items=_str_list(g, "items", f"skill_groups[{i}]")))
    education = []
    for i, ed in enumerate(raw.get("education") or []):
        if not isinstance(ed, dict):
            raise ConfigError(f"{where}: education[{i}] must be a mapping")
        w = f"education[{i}]"
        education.append(Education(
            degree=_str(ed, "degree", w), school=_str(ed, "school", w),
            location=_str(ed, "location", w, required=False), start=_str(ed, "start", w),
            end=_end(ed, w),
        ))
    languages = []
    for i, lg in enumerate(raw.get("languages") or []):
        if not isinstance(lg, dict):
            raise ConfigError(f"{where}: languages[{i}] must be a mapping")
        languages.append(Language(name=_str(lg, "name", f"languages[{i}]"),
                                  level=_str(lg, "level", f"languages[{i}]")))
    if not experiences:
        raise ConfigError(f"{where}: at least one experience is required")
    skills = []
    for i, sk in enumerate(raw.get("skills") or []):
        if not isinstance(sk, dict):
            raise ConfigError(f"{where}: skills[{i}] must be a mapping {{id, label}}")
        w = f"skills[{i}]"
        sid = " ".join(_str(sk, "id", w).lower().split())
        skills.append(Skill(id=sid, label=_str(sk, "label", w)))
    return Master(
        headline=_str(raw, "headline", where),
        target=_str(raw, "target", where),
        available_from=_str(raw, "available_from", where),
        mobility=_str(raw, "mobility", where, required=False),
        experiences=experiences,
        projects=projects,
        skills=skills,
        skill_groups=groups,
        education=education,
        certifications=_str_list(raw, "certifications", where),
        languages=languages,
        extras=_str_list(raw, "extras", where),
    )


def parse_contact(raw: object, where: str = "contact.yaml") -> Contact:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a mapping")
    extra = set(raw) - set(CONTACT_KEYS)
    if extra:
        raise ConfigError(f"{where}: unknown keys: {', '.join(sorted(extra))}")
    values = {k: _str(raw, k, where, required=k in ("first_name", "last_name", "email"))
              for k in CONTACT_KEYS}
    return Contact(**values)


def _load_yaml(path: Path) -> object:
    if not path.exists():
        raise ConfigError(f"File not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_master(path: Path) -> Master:
    return parse_master(_load_yaml(path), str(path))


def load_contact(path: Path) -> Contact:
    return parse_contact(_load_yaml(path), str(path))


def to_json(obj: Master | Contact) -> str:
    """The object as the Worker reads it from R2: sorted keys, no trailing data."""
    return json.dumps(asdict(obj), ensure_ascii=False, sort_keys=True, indent=1)
