import re

from job_match.config.schema import Profile, Settings
from job_match.domain.models import Job, ScoreResult


class NativeRuleScorer:
    def __init__(self, aliases: dict[str, list[str]]) -> None:
        self._aliases = aliases

    @property
    def name(self) -> str:
        return "native"

    def _forms(self, skill_name: str) -> list[str]:
        canonical = skill_name.lower()
        return [canonical] + [a.lower() for a in self._aliases.get(canonical, [])]

    def _matches(self, form: str, text: str) -> bool:
        pattern = r"(?<!\w)" + re.escape(form) + r"(?!\w)"
        return bool(re.search(pattern, text, re.IGNORECASE))

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult:
        text = f"{job.title} {job.description}".lower()
        title_text = job.title.lower()

        delta = 0
        positive_matches: list[str] = []
        negative_matches: list[str] = []
        missing_preferences: list[str] = []
        explanations: list[str] = []

        for skill in profile.skills.preferred:
            if any(self._matches(form, text) for form in self._forms(skill.name)):
                positive_matches.append(skill.name)
                delta += skill.weight
                explanations.append(f"Matched preferred: {skill.name} (+{skill.weight})")
            else:
                missing_preferences.append(skill.name)
                explanations.append(f"Missed preferred: {skill.name}")

        for skill in profile.skills.negative:
            if any(self._matches(form, text) for form in self._forms(skill.name)):
                negative_matches.append(skill.name)
                delta += skill.weight
                explanations.append(f"Matched negative: {skill.name} ({skill.weight})")

        matched_kws = [
            kw for kw in profile.ft_search.keywords
            if self._matches(kw.lower(), title_text)
        ]
        if matched_kws:
            delta += settings.title_bonus
            explanations.append(
                f"Title keyword match: {matched_kws[0]} (+{settings.title_bonus})"
            )

        final_score = max(0, min(100, settings.base_score + delta))

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
            },
        )
