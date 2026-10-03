import pytest

from backend.app.storage import db


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    # Every test gets its own fresh, isolated SQLite file — a plain re-init
    # per test (init_db has no guard against being called twice, so this is
    # harmless even for tests that call it again themselves with their own
    # tmp_path). Needed because adapter.analyze() now reads
    # db.rating_distribution() on every call, not just in tests that already
    # set up a DB explicitly.
    db.init_db(f"sqlite:///{tmp_path / 'test.db'}")
