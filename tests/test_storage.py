import pytest
from backend.app.storage import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db.init_db(f"sqlite:///{tmp_path / 'test.db'}")
    yield


def test_upsert_and_get_run_round_trip():
    db.upsert_run({"id": "abc123", "kind": "live", "symbol": "PETR4.SA", "status": "RUNNING", "started_at": "t0", "logs": []})
    row = db.get_run("abc123")
    assert row["status"] == "RUNNING"
    assert row["symbol"] == "PETR4.SA"
    assert row["logs"] == []

    db.upsert_run({"id": "abc123", "status": "COMPLETED", "decision": "HOLD", "finished_at": "t1", "quote": {"price": 10}})
    row = db.get_run("abc123")
    assert row["status"] == "COMPLETED"
    assert row["decision"] == "HOLD"
    assert row["quote"] == {"price": 10}


def test_reconcile_orphan_runs_marks_running_as_error_and_never_completed():
    db.upsert_run({"id": "run-1", "kind": "live", "symbol": "PETR4.SA", "status": "RUNNING", "started_at": "t0"})
    ids = db.reconcile_orphan_runs("Execução interrompida por reinício do servidor.")
    assert ids == ["run-1"]
    row = db.get_run("run-1")
    assert row["status"] == "ERROR"
    assert "reinício" in row["error"]
    assert row["status"] != "COMPLETED"


def test_reconcile_is_a_noop_when_nothing_is_running():
    db.upsert_run({"id": "run-2", "kind": "live", "symbol": "PETR4.SA", "status": "COMPLETED", "started_at": "t0", "decision": "BUY"})
    ids = db.reconcile_orphan_runs("mensagem")
    assert ids == []
    row = db.get_run("run-2")
    assert row["status"] == "COMPLETED"
    assert row["decision"] == "BUY"


def test_get_last_run_returns_most_recent_by_kind():
    db.upsert_run({"id": "r1", "kind": "live", "symbol": "PETR4.SA", "status": "COMPLETED", "started_at": "2026-01-01T00:00:00"})
    db.upsert_run({"id": "r2", "kind": "live", "symbol": "VALE3.SA", "status": "ERROR", "started_at": "2026-01-02T00:00:00"})
    last = db.get_last_run("live")
    assert last["id"] == "r2"


def test_init_db_adds_missing_pid_column_to_pre_existing_file(tmp_path):
    """A DB file created before the ``pid`` column existed (e.g. a stale
    deploy) must not crash every query afterwards; init_db must migrate it."""
    import sqlite3
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, backtest_job_id TEXT, symbol TEXT NOT NULL, "
        "trade_date TEXT, status TEXT NOT NULL, decision TEXT, rating_5tier TEXT, summary TEXT, model TEXT, "
        "provider TEXT, started_at TEXT, finished_at TEXT, error TEXT, quote_json TEXT, logs_json TEXT, "
        "raw_return REAL, alpha_return REAL, benchmark TEXT, holding_days INTEGER, resolution_date TEXT)"
    )
    conn.commit()
    conn.close()

    db.init_db(f"sqlite:///{path}")
    db.upsert_run({"id": "legacy-1", "kind": "live", "symbol": "PETR4.SA", "status": "RUNNING", "started_at": "t0", "pid": 4242})
    row = db.get_run("legacy-1")
    assert row["pid"] == 4242


def test_backtest_job_lifecycle():
    db.create_backtest_job({"id": "job-1", "symbol": "PETR4.SA", "start_date": "2026-01-01", "end_date": "2026-01-05", "holding_days": 5, "status": "QUEUED", "created_at": "t0", "total_dates": 3})
    db.update_backtest_job("job-1", status="RUNNING", completed_dates=1, current_date="2026-01-02")
    job = db.get_backtest_job("job-1")
    assert job["status"] == "RUNNING"
    assert job["completed_dates"] == 1

    orphaned = db.reconcile_orphan_backtest_jobs("Job interrompido por reinício do servidor.")
    assert orphaned == ["job-1"]
    job = db.get_backtest_job("job-1")
    assert job["status"] == "ERROR"
