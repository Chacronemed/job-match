"""private/apply.yaml (gitignored): the answers a form asks that no model may write (ADR 0023).

- `remuneration`: `mode: manuel` (default) means a salary field is never filled: it is
  highlighted and the zone's benchmark (`reperes`) is shown. `mode: fourchette` fills the
  range I set (`fourchette: {min, max, devise, periode}`), never another number.
- `preavis`, `mobilite`: fixed texts (`mobilite` overrides the master's `mobility`).
- `reponses_fixes`: `{label, match: [words], reponse, label_en?}`: a question whose label holds
  one of the words gets `reponse` (work authorization, driving licence...). On a select or a
  radio, the option may read `reponse`, `label_en` (its English form) or an equivalent of
  either (`option_equivalents` in config/apply_questions.yaml: oui/yes, CDI/permanent...).

Pushed to R2 next to the master by `job-match cv push` (the offer page shows the kit), read
locally by `job-match apply`. Never sent to a model.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from job_match.config.schema import ConfigError

MODES = ("manuel", "fourchette")
APPLY_KEY = "master/apply.json"


@dataclass(frozen=True)
class SalaryRange:
    min: int
    max: int
    devise: str = "€"
    periode: str = "brut annuel"


@dataclass(frozen=True)
class Benchmark:
    zone: str
    texte: str
    match: list[str] = field(default_factory=list)  # empty: the default zone


@dataclass(frozen=True)
class Remuneration:
    mode: str = "manuel"
    fourchette: SalaryRange | None = None
    reperes: list[Benchmark] = field(default_factory=list)


@dataclass(frozen=True)
class FixedAnswer:
    label: str
    match: list[str]
    reponse: str
    label_en: str = ""  # the answer as an English form's option reads it


@dataclass(frozen=True)
class ApplyConfig:
    remuneration: Remuneration = field(default_factory=Remuneration)
    preavis: str = ""
    mobilite: str = ""
    reponses_fixes: list[FixedAnswer] = field(default_factory=list)


def _text(raw: dict, key: str, where: str, *, required: bool = False) -> str:
    v = raw.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ConfigError(f"{where}: missing {key}")
        return ""
    if not isinstance(v, str):
        raise ConfigError(f"{where}: {key} must be a string")
    return v.strip()


def _words(raw: dict, key: str, where: str) -> list[str]:
    v = raw.get(key) or []
    if not isinstance(v, list) or not all(isinstance(w, str) and w.strip() for w in v):
        raise ConfigError(f"{where}: {key} must be a list of non-empty strings")
    return [w.strip() for w in v]


def _amount(raw: dict, key: str, where: str) -> int:
    v = raw.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ConfigError(f"{where}: {key} must be a positive integer")
    return v


def parse_apply(raw: object, where: str = "apply.yaml") -> ApplyConfig:
    if raw is None:
        return ApplyConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a mapping")
    unknown = set(raw) - {"remuneration", "preavis", "mobilite", "reponses_fixes"}
    if unknown:
        raise ConfigError(f"{where}: unknown keys: {', '.join(sorted(unknown))}")
    rem_raw = raw.get("remuneration") or {}
    if not isinstance(rem_raw, dict):
        raise ConfigError(f"{where}: remuneration must be a mapping")
    mode = rem_raw.get("mode", "manuel")
    if mode not in MODES:
        raise ConfigError(f"{where}: remuneration.mode must be one of {', '.join(MODES)}")
    rng = None
    if rem_raw.get("fourchette") is not None:
        f = rem_raw["fourchette"]
        w = f"{where}: remuneration.fourchette"
        if not isinstance(f, dict):
            raise ConfigError(f"{w} must be a mapping")
        rng = SalaryRange(min=_amount(f, "min", w), max=_amount(f, "max", w),
                          devise=_text(f, "devise", w) or "€",
                          periode=_text(f, "periode", w) or "brut annuel")
        if rng.min > rng.max:
            raise ConfigError(f"{w}: min is above max")
    if mode == "fourchette" and rng is None:
        raise ConfigError(f"{where}: remuneration.mode fourchette needs remuneration.fourchette")
    reperes = []
    for i, r in enumerate(rem_raw.get("reperes") or []):
        w = f"{where}: remuneration.reperes[{i}]"
        if not isinstance(r, dict):
            raise ConfigError(f"{w} must be a mapping")
        reperes.append(Benchmark(zone=_text(r, "zone", w, required=True),
                                 texte=_text(r, "texte", w, required=True),
                                 match=_words(r, "match", w)))
    fixed = []
    for i, a in enumerate(raw.get("reponses_fixes") or []):
        w = f"{where}: reponses_fixes[{i}]"
        if not isinstance(a, dict):
            raise ConfigError(f"{w} must be a mapping")
        words = _words(a, "match", w)
        if not words:
            raise ConfigError(f"{w}: match needs at least one word")
        fixed.append(FixedAnswer(label=_text(a, "label", w, required=True), match=words,
                                 reponse=_text(a, "reponse", w, required=True),
                                 label_en=_text(a, "label_en", w)))
    return ApplyConfig(
        remuneration=Remuneration(mode=mode, fourchette=rng, reperes=reperes),
        preavis=_text(raw, "preavis", where),
        mobilite=_text(raw, "mobilite", where),
        reponses_fixes=fixed,
    )


def load_apply(path: Path) -> ApplyConfig:
    """The file, or the defaults (salary `manuel`, nothing fixed) when it does not exist."""
    if not path.exists():
        return ApplyConfig()
    with path.open(encoding="utf-8") as fh:
        return parse_apply(yaml.safe_load(fh), str(path))


def to_json(cfg: ApplyConfig) -> str:
    """As the Worker and kit.js read it. In `manuel` the range is left out entirely: no
    salary value leaves the machine when none may be filled."""
    data = asdict(cfg)
    if cfg.remuneration.mode == "manuel":
        data["remuneration"]["fourchette"] = None
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)
