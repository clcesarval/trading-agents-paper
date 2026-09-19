import asyncio

import pytest

from backend.app.backtest import service as service_module
from backend.app.backtest.service import BacktestService
from backend.app.storage import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    db.init_db(f"sqlite:///{tmp_path / 'test.db'}")
    yield


@pytest.fixture(autouse=True)
def no_real_price_fetch(monkeypatch):
    # _compute_realized_return hits yfinance directly; every test here cares
    # about job/run status bookkeeping, not the return calculation itself.
    monkeypatch.setattr(service_module, "_compute_realized_return", lambda *a, **k: (None, None, None, None, "^BVSP"))


class _AlwaysFailsAdapter:
    async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
        raise RuntimeError("Ollama indisponível")


class _AlwaysOkAdapter:
    async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
        return {"decision": "HOLD", "rating_5tier": "Hold", "is_review": False, "model": "qwen2.5:3b", "provider": "ollama", "summary": "ok"}


@pytest.mark.asyncio
async def test_job_status_is_error_when_every_date_fails():
    # A 1-day job whose only date times out must not report DONE — a
    # "concluded" badge next to a table with a single ERROR row is a
    # misleading success reading of an all-failure run (reported live).
    service = BacktestService(_AlwaysFailsAdapter(), asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5)
    await service.run_job(job["id"])

    final_job = db.get_backtest_job(job["id"])
    assert final_job["status"] == "ERROR"
    assert final_job["error"]

    runs = db.list_runs(kind="backtest", backtest_job_id=job["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "ERROR"


@pytest.mark.asyncio
async def test_job_status_is_done_when_at_least_one_date_succeeds():
    service = BacktestService(_AlwaysOkAdapter(), asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5)
    await service.run_job(job["id"])

    final_job = db.get_backtest_job(job["id"])
    assert final_job["status"] == "DONE"

    runs = db.list_runs(kind="backtest", backtest_job_id=job["id"])
    assert runs[0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_retry_only_reruns_the_failed_dates():
    dates = service_module._business_dates("2026-05-01", "2026-05-08")
    assert len(dates) >= 2, "need at least 2 business days for this test to mean anything"
    fail_date = dates[-1]
    attempts: dict[str, int] = {}

    class _FailsOnFirstAttemptAdapter:
        async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
            attempts[trade_date] = attempts.get(trade_date, 0) + 1
            if trade_date == fail_date and attempts[trade_date] == 1:
                raise RuntimeError("timeout simulado")
            return {"decision": "BUY", "rating_5tier": "Buy", "is_review": False, "model": "qwen2.5:3b", "provider": "ollama", "summary": "ok"}

    service = BacktestService(_FailsOnFirstAttemptAdapter(), asyncio.Lock())
    job = service.create_job("PETR4", dates[0], dates[-1], 5)
    await service.run_job(job["id"])

    first_pass = db.get_backtest_job(job["id"])
    assert first_pass["status"] == "DONE"  # some dates succeeded despite the one failure
    errored_dates = [r["trade_date"] for r in db.list_runs(kind="backtest", backtest_job_id=job["id"]) if r["status"] == "ERROR"]
    assert errored_dates == [fail_date]
    assert all(attempts[d] == 1 for d in dates)  # every date attempted exactly once so far

    await service.run_job(job["id"])  # retry: same job_id, same call signature as the API endpoint uses

    # Only the previously-failed date was attempted again; already-resolved dates were skipped entirely.
    assert attempts[fail_date] == 2
    assert all(attempts[d] == 1 for d in dates if d != fail_date)
    final_runs = {r["trade_date"]: r["status"] for r in db.list_runs(kind="backtest", backtest_job_id=job["id"])}
    assert all(status == "COMPLETED" for status in final_runs.values())
