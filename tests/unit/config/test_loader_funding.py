from job_match.config.loader import load_settings


def test_settings_funding_lead_dedup_days_default_and_parsed(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("funding:\n  sources: [maddyness]\n", encoding="utf-8")
    assert load_settings(path).funding.lead_dedup_days == 30
    path.write_text("funding:\n  lead_dedup_days: 7\n", encoding="utf-8")
    assert load_settings(path).funding.lead_dedup_days == 7
