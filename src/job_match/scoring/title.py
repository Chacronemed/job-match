"""What the title says the job is: the target family, an adjacent IT role, another trade, or
none of them (config `title_relevance`, schema.TitleRelevanceConfig).

The title decides because the description lies by omission: a recruiter post that mentions
Docker, or a hardware test bench in a defence plant, passed the skill gate and scored like a
DevOps job (docs/diagnostics/m24-scoring.md). The order is the rule:

1. a core term wins ("Ingénieur DevOps commercial"…), unless the title also names a role
   that is not ours (core_overrides: sales, product owner, project manager, recruiter): then
   it is "other", a penalty, never a veto;
2. another trade wins over a near term ("Ingénieur systèmes embarqués" is out);
3. a near term wins over a sector word ("Data engineer - marketing" stays near);
4. a sector word alone is out ("Technicien logistique").
"""
from __future__ import annotations

from dataclasses import dataclass

from job_match.config.schema import TitleRelevanceConfig
from job_match.normalization.skills import title_keyword, title_term

CORE = "core"
NEAR = "near"
OTHER = "other"
OFF_DOMAIN = "off_domain"


@dataclass(frozen=True)
class TitleFamily:
    family: str        # core | near | other | off_domain
    term: str | None   # the configured term that decided, None for "other" with no term
    points: int        # added to the score; off_domain never reaches the scorer (vetoed)


def title_family(title: str, cfg: TitleRelevanceConfig) -> TitleFamily:
    """The family of `title`. Callers check `cfg.enabled` first."""
    if term := title_keyword(title, cfg.core):
        if role := title_term(title, cfg.core_overrides):
            return TitleFamily(OTHER, role, cfg.other_points)
        return TitleFamily(CORE, term, cfg.core_points)
    if term := title_keyword(title, cfg.off_domain):
        return TitleFamily(OFF_DOMAIN, term, 0)
    if term := title_keyword(title, cfg.near):
        return TitleFamily(NEAR, term, cfg.near_points)
    if term := title_keyword(title, cfg.off_domain_sectors):
        return TitleFamily(OFF_DOMAIN, term, 0)
    return TitleFamily(OTHER, None, cfg.other_points)


def is_off_domain(title: str, cfg: TitleRelevanceConfig) -> bool:
    """The gate's veto: another trade (or a sector with no IT role) named in the title."""
    return cfg.enabled and title_family(title, cfg).family == OFF_DOMAIN
