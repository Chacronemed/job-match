"""One set of statuses and labels in four places: D1 schema, Worker, dashboard, Python."""
import re
from pathlib import Path

from job_match.tracking.constants import LABELS, NOTE_MAX, SKILL_MAX, SKILL_RE, STATUSES

ROOT = Path(__file__).parent.parent.parent.parent
D1 = (ROOT / "worker" / "migrations" / "0001_tracking.sql").read_text(encoding="utf-8")
D1_OVERRIDES = (ROOT / "worker" / "migrations" / "0002_skill_overrides.sql").read_text(
    encoding="utf-8"
)
WORKER = (ROOT / "worker" / "src" / "validate.js").read_text(encoding="utf-8")
DASHBOARD = (ROOT / "src" / "job_match" / "dashboard" / "assets" / "tracking.js").read_text(
    encoding="utf-8"
)


def _check_list(column: str) -> tuple[str, ...]:
    m = re.search(rf"{column}\s+IN\s*\(([^)]*)\)", D1)
    assert m, column
    return tuple(re.findall(r"'([a-z_]+)'", m.group(1)))


def _js_array(source: str, name: str) -> tuple[str, ...]:
    m = re.search(rf"{name}\s*=\s*\[([^\]]*)\]", source)
    assert m, name
    return tuple(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_statuses_agree_everywhere():
    assert _check_list("status") == STATUSES
    assert _js_array(WORKER, "STATUSES") == STATUSES
    assert _js_array(DASHBOARD, "STATUSES") == STATUSES


def test_labels_agree_everywhere():
    assert _check_list("label") == LABELS
    assert _js_array(WORKER, "LABELS") == LABELS
    assert _js_array(DASHBOARD, "LABELS") == LABELS


def test_every_status_and_label_has_display_text():
    for value in STATUSES + LABELS:
        assert re.search(rf"\b{value}: \"[A-Z][a-z ]+\"", DASHBOARD), value


def test_note_limit_agrees_everywhere():
    assert f"length(note) <= {NOTE_MAX}" in D1
    assert f"NOTE_MAX = {NOTE_MAX}" in WORKER
    assert f"NOTE_MAX = {NOTE_MAX}" in DASHBOARD


def test_mirror_migration_has_the_d1_columns():
    mirror = (ROOT / "src" / "job_match" / "migrations" / "0008_tracking_mirror.sql").read_text(
        encoding="utf-8"
    )
    for column in ("job_key", "status", "applied_at", "follow_up_at", "note", "cv_url",
                   "updated_at", "label", "score_at_decision", "created_at"):
        assert column in D1 and column in mirror, column


def test_skill_name_rule_agrees_everywhere():
    js_pattern = SKILL_RE.pattern.removesuffix(r"\Z") + "$"
    assert f"const SKILL_RE = /{js_pattern}/;" in WORKER
    assert f"SKILL_MAX = {SKILL_MAX}" in WORKER
    assert f"length(skill) <= {SKILL_MAX}" in D1_OVERRIDES
    mirror = (ROOT / "src" / "job_match" / "migrations" / "0009_skill_overrides_mirror.sql")
    for column in ("skill", "created_at"):
        assert column in D1_OVERRIDES and column in mirror.read_text(encoding="utf-8")


def test_the_committed_vocabulary_passes_the_skill_name_rule():
    from job_match.config.loader import load_skill_vocabulary

    vocab = load_skill_vocabulary(ROOT / "config" / "skill_vocabulary.yaml")
    assert vocab
    for term in vocab:
        assert SKILL_RE.match(term), term
