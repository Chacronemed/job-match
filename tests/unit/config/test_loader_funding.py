from job_match.config.loader import load_settings


def test_settings_funding_lead_dedup_days_default_and_parsed(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("funding:\n  sources: [maddyness]\n", encoding="utf-8")
    assert load_settings(path).funding.lead_dedup_days == 30
    path.write_text("funding:\n  lead_dedup_days: 7\n", encoding="utf-8")
    assert load_settings(path).funding.lead_dedup_days == 7


def test_quality_sections_defaults(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("strong_threshold: 70\n", encoding="utf-8")
    s = load_settings(path)
    assert s.relevance.target_title_keywords == []
    assert (s.digest.min_score, s.digest.max_leads) == (60, 10)
    assert s.funding.lead_filters.countries == ["France"]
    assert s.funding.lead_filters.min_amount_eur is None


def test_quality_sections_parsed(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "relevance:\n  target_title_keywords: [devops, infra]\n"
        "digest:\n  min_score: 65\n  max_leads: 5\n"
        "funding:\n  lead_filters:\n    countries: []\n    min_amount_eur: 1000000\n"
        "    exclude_sectors: [crypto]\n    fx_to_eur: {usd: 0.9}\n",
        encoding="utf-8",
    )
    s = load_settings(path)
    assert s.relevance.target_title_keywords == ["devops", "infra"]
    assert (s.digest.min_score, s.digest.max_leads) == (65, 5)
    lf = s.funding.lead_filters
    assert (lf.countries, lf.min_amount_eur, lf.exclude_sectors) == ([], 1e6, ["crypto"])
    assert lf.fx_to_eur == {"USD": 0.9}


def test_committed_settings_enable_the_relevance_gate():
    from pathlib import Path

    s = load_settings(Path(__file__).parents[3] / "config" / "settings.yaml")
    assert "devops" in s.relevance.target_title_keywords
