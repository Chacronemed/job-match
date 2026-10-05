from job_match.config.schema import Profile, Settings
from job_match.domain.models import Job, ScoreResult
from job_match.normalization.skills import contains_term, matches_skill


class NativeRuleScorer:
    def __init__(self, aliases: dict[str, list[str]]) -> None:
        self._aliases = aliases

    @property
    def name(self) -> str:
        return "native"

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult:
        text = f"{job.title} {job.description}".lower()
        title_text = job.title.lower()

        delta = 0
        positive_matches: list[str] = []
        negative_matches: list[str] = []
        missing_preferences: list[str] = []
        explanations: list[str] = []

        for skill in profile.skills.preferred:
            if matches_skill(text, skill.name, self._aliases):
                positive_matches.append(skill.name)
                delta += skill.weight
                explanations.append(f"Matched preferred: {skill.name} (+{skill.weight})")
            else:
                missing_preferences.append(skill.name)
                explanations.append(f"Missed preferred: {skill.name}")

        for skill in profile.skills.negative:
            if matches_skill(text, skill.name, self._aliases):
                negative_matches.append(skill.name)
                delta += skill.weight
                explanations.append(f"Matched negative: {skill.name} ({skill.weight})")

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
