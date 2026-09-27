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


class _AlwaysInconclusiveAdapter:
    async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
        return {"decision": None, "rating_5tier": "REVIEW", "is_review": True, "model": "qwen2.5:3b", "provider": "ollama", "summary": "sem rating reconhecível"}


def test_b3_ticker_is_priced_with_sa_suffix_and_benchmarked_against_ibovespa():
    # A bare "PETR4" made Yahoo answer 404 and the return silently came back
    # empty; the benchmark also fell back to SPY for a Brazilian stock.
    assert service_module._price_ticker("PETR4") == "PETR4.SA"
    assert service_module._price_ticker("petr4.sa") == "PETR4.SA"
    assert service_module._resolve_benchmark("PETR4") == "^BVSP"
    assert service_module._resolve_benchmark("AAPL") == "SPY"


@pytest.mark.asyncio
async def test_retry_backfills_missing_return_without_rerunning_the_ai(monkeypatch):
    calls = []

    class _CountingAdapter:
        async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
            calls.append(trade_date)
            return {"decision": "HOLD", "rating_5tier": "Hold", "is_review": False, "model": "m", "provider": "ollama", "summary": "ok"}

    service = BacktestService(_CountingAdapter(), asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-04", "2026-05-04", 5)
    await service.run_job(job["id"])  # return calculation fails (fixture returns Nones)
    run_id = f"{job['id']}-2026-05-04"
    assert db.get_run(run_id)["raw_return"] is None

    monkeypatch.setattr(service_module, "_compute_realized_return", lambda *a, **k: (-0.059, -0.03, 5, "2026-05-11", "^BVSP"))
    await service.run_job(job["id"])

    assert calls == ["2026-05-04"]  # AI ran once, not again on the backfill
    row = db.get_run(run_id)
    assert row["raw_return"] == -0.059 and row["alpha_return"] == -0.03 and row["benchmark"] == "^BVSP"


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


class _SequencedAdapter:
    """Returns a different decision on each successive call — used to
    reproduce, deterministically, the real case of the same date flipping
    between Buy/Hold/Sell across independent attempts."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
        decision = self.decisions[self.calls]
        self.calls += 1
        rating = {"BUY": "Buy", "HOLD": "Hold", "SELL": "Sell", None: "REVIEW"}[decision]
        is_review = decision is None
        return {"decision": decision, "rating_5tier": rating, "is_review": is_review, "model": "m", "provider": "ollama", "summary": "ok"}


@pytest.mark.asyncio
async def test_consensus_runs_takes_the_majority_decision_across_attempts():
    adapter = _SequencedAdapter(["BUY", "BUY", "HOLD"])
    service = BacktestService(adapter, asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5, consensus_runs=3)
    await service.run_job(job["id"])

    assert adapter.calls == 3
    run = db.get_run(f"{job['id']}-2026-05-01")
    assert run["status"] == "COMPLETED" and run["decision"] == "BUY"
    assert "consenso" in run["rating_5tier"].lower() and "2/3" in run["rating_5tier"]
    assert run["consensus_detail"]["decision"] == "BUY" and run["consensus_detail"]["runs"] == 3


@pytest.mark.asyncio
async def test_consensus_runs_with_no_majority_is_inconclusive_but_not_an_error():
    # Real case: PETR4 2026-08-17 came back Buy, Hold, Hold, Buy across four
    # separate attempts — no strict majority, so the date must report that
    # instability instead of silently picking one side.
    adapter = _SequencedAdapter(["BUY", "HOLD"])
    service = BacktestService(adapter, asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5, consensus_runs=2)
    await service.run_job(job["id"])

    run = db.get_run(f"{job['id']}-2026-05-01")
    assert run["status"] == "INCONCLUSIVE" and run["decision"] is None
    assert "sem consenso" in run["rating_5tier"].lower()
    assert run["consensus_detail"]["decision"] is None
    final_job = db.get_backtest_job(job["id"])
    assert final_job["status"] == "DONE"  # instability is a real, resolved outcome, not a failure


@pytest.mark.asyncio
async def test_consensus_runs_defaults_to_one_and_keeps_the_old_behavior_unchanged():
    calls = []

    class _CountingAdapter:
        async def analyze(self, symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None, cancel_check=None):
            calls.append(1)
            return {"decision": "HOLD", "rating_5tier": "Hold", "is_review": False, "model": "m", "provider": "ollama", "summary": "ok"}

    service = BacktestService(_CountingAdapter(), asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5)  # consensus_runs omitted
    await service.run_job(job["id"])

    assert len(calls) == 1
    run = db.get_run(f"{job['id']}-2026-05-01")
    assert run["rating_5tier"] == "Hold"  # no "(consenso ...)" suffix added for a single attempt
    assert run["consensus_detail"] is None


@pytest.mark.asyncio
async def test_reset_date_forces_a_redo_of_an_already_resolved_date():
    # An INCONCLUSIVE (REVIEW) date is a real, resolved outcome, so a plain
    # retry correctly skips it — but the user may still want another attempt
    # at a real decision. reset_date() is the explicit "redo this one" escape
    # hatch, independent of whether it "needs" retrying by the usual rule.
    swappable_adapter = _AlwaysInconclusiveAdapter()
    service = BacktestService(swappable_adapter, asyncio.Lock())
    job = service.create_job("PETR4", "2026-05-01", "2026-05-01", 5)
    await service.run_job(job["id"])

    run_before = db.get_run(f"{job['id']}-2026-05-01")
    assert run_before["status"] == "INCONCLUSIVE"

    # A plain retry must leave the already-resolved INCONCLUSIVE date alone.
    await service.run_job(job["id"])
    assert db.get_run(f"{job['id']}-2026-05-01")["status"] == "INCONCLUSIVE"

    # Swap in an adapter that gives a real decision, then force a redo.
    service.adapter = _AlwaysOkAdapter()
    service.reset_date(job["id"], "2026-05-01")
    assert db.get_run(f"{job['id']}-2026-05-01")["status"] == "QUEUED"

    await service.run_job(job["id"])
    final_run = db.get_run(f"{job['id']}-2026-05-01")
    assert final_run["status"] == "COMPLETED"
    assert final_run["decision"] == "HOLD"
    final_job = db.get_backtest_job(job["id"])
    assert final_job["status"] == "DONE"
