"""Dashboard fixtures: the seeded snapshot the data and render tests inspect."""
import pytest

from job_match.config.schema import Settings
from job_match.dashboard.data import build_dashboard_data
from job_match.persistence.db import Database


@pytest.fixture
def dashboard_data(seed_dashboard):
    """`(data, seed)`: the generator's output for the shared seed, with default settings."""
    with Database(path=":memory:") as db:
        seed = seed_dashboard(db)
        data = build_dashboard_data(db, Settings(), seed.now)
    return data, seed
