from job_match.adapters.jobs.base import source_payload


def test_source_payload_drops_only_adapter_annotations():
    raw = {"id": "X", "intitule": "DevOps", "_jm_query": "devops", "_jm_region": "IDF"}
    assert source_payload(raw) == {"id": "X", "intitule": "DevOps"}
    assert raw["_jm_query"] == "devops"  # the adapter still needs it for to_job
