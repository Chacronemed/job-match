import math

from job_match.config.schema import Profile, Settings
from job_match.domain.models import Job, ScoreResult
from job_match.normalization.sections import profile_text
from job_match.normalization.skills import contains_term, find_skill, snippet
from job_match.scoring.title import title_family


def profile_weight(weight: int, multiplier: float) -> int:
    """A skill's weight when the offer asks for it in its profile section, rounded half up
    (3 x 1.5 = 5, not banker's 4)."""
    return int(math.floor(weight * multiplier + 0.5))


class NativeRuleScorer:
    """`vocabulary`: skills worth naming when an offer asks for them and the profile does
    not list them (`config/skill_vocabulary.yaml`). They never change the score."""

    def __init__(
        self, aliases: dict[str, list[str]], vocabulary: tuple[str, ...] | list[str] = ()
    ) -> None:
        self._aliases = aliases
        self._vocabulary = tuple(vocabulary)

    @property
    def name(self) -> str:
        return "native"

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult:
        # Original case: matching ignores it, and the evidence sentences read better.
        text = f"{job.title}. {job.description}"
        title_text = job.title.lower()
        evidence: dict[str, str] = {}
        weights: dict[str, int] = {}
        multiplier = settings.scoring.profile_section_multiplier
        profile_part = profile_text(job.description) if multiplier != 1 else ""

        delta = 0
        positive_matches: list[str] = []
        negative_matches: list[str] = []
        missing_preferences: list[str] = []
        explanations: list[str] = []

        for skill in profile.skills.preferred:
            if m := find_skill(text, skill.name, self._aliases):
                weight = skill.weight
                # Asked for in the profile / skills section: worth more than a passing mention.
                if profile_part and find_skill(profile_part, skill.name, self._aliases):
                    weight = profile_weight(skill.weight, multiplier)
                    explanations.append(f"Profile section: {skill.name} (x{multiplier:g})")
                evidence[skill.name] = snippet(text, m.start(), m.end())
                weights[skill.name] = weight
                positive_matches.append(skill.name)
                delta += weight
                explanations.append(f"Matched preferred: {skill.name} (+{weight})")
            else:
                missing_preferences.append(skill.name)
                explanations.append(f"Missed preferred: {skill.name}")

        for skill in profile.skills.negative:
            if m := find_skill(text, skill.name, self._aliases):
                evidence[skill.name] = snippet(text, m.start(), m.end())
                weights[skill.name] = skill.weight
                negative_matches.append(skill.name)
                delta += skill.weight
                explanations.append(f"Matched negative: {skill.name} ({skill.weight})")

        # What the title says the job is (title_relevance) replaces the older keyword bonus,
        # so a DevOps title is never counted twice. Without that config, the bonus stays.
        family = None
        matched_kws: list[str] = []
        if settings.title_relevance.enabled:
            family = title_family(job.title, settings.title_relevance)
            delta += family.points
            sign = "+" if family.points >= 0 else ""
            explanations.append(f"Title relevance: {family.family} ({sign}{family.points})")
        else:
            matched_kws = [
                kw for kw in profile.ft_search.keywords
                if contains_term(title_text, kw.lower())
            ]
            if matched_kws:
                delta += settings.title_bonus
                explanations.append(
                    f"Title keyword match: {matched_kws[0]} (+{settings.title_bonus})"
                )

        final_score = max(0, min(100, settings.base_score + delta))

        listed = {
            s.name.lower() for s in (*profile.skills.preferred, *profile.skills.negative)
        }
        unlisted: dict[str, str] = {}
        for term in self._vocabulary:
            if term.lower() in listed:
                continue
            if m := find_skill(text, term, self._aliases):
                unlisted[term] = snippet(text, m.start(), m.end())

        return ScoreResult(
            engine="native",
            available=True,
            score=final_score,
            positive_matches=tuple(positive_matches),
            negative_matches=tuple(negative_matches),
            missing_preferences=tuple(missing_preferences),
            explanations=tuple(explanations),
            raw={
                "base_score": settings.base_score,
                "delta": delta,
                "title_keywords_matched": matched_kws,
                "title_family": family.family if family else None,
            },
            evidence=evidence,
            weights=weights,
            unlisted=unlisted,
        )
