import time
import pytest
from backend.app.execution import runner as runner_module
from backend.app.execution.runner import run_isolated, AnalysisCancelled, AnalysisTimeout
from tests._slow_target import slow_worker


@pytest.mark.asyncio
async def test_slow_process_is_actually_terminated_on_timeout(monkeypatch):
    monkeypatch.setattr(runner_module, "run_worker", slow_worker)
    events = []
    started = time.monotonic()
    with pytest.raises(AnalysisTimeout):
        await run_isolated({"sleep_seconds": 30}, events.append, timeout=1.0)
    elapsed = time.monotonic() - started
    # Proves the coroutine did not sit through the full 30s sleep: the child
    # process was actually killed, not just abandoned like the old
    # asyncio.to_thread approach.
    assert elapsed < 10


@pytest.mark.asyncio
async def test_fast_process_returns_result_within_timeout(monkeypatch):
    monkeypatch.setattr(runner_module, "run_worker", slow_worker)
    pids = []
    result = await run_isolated({"sleep_seconds": 0}, lambda e: None, timeout=15.0, on_start=pids.append)
    assert result["signal"] == "Hold"
    assert result["is_review"] is False
    assert len(pids) == 1


@pytest.mark.asyncio
async def test_cancel_check_kills_the_process_immediately(monkeypatch):
    # A backtest's "cancel" button must stop the in-flight date right away,
    # not only once it happens to finish on its own (previously the only way
    # out was the full analysis timeout, minutes away).
    monkeypatch.setattr(runner_module, "run_worker", slow_worker)
    started = time.monotonic()
    with pytest.raises(AnalysisCancelled):
        await run_isolated({"sleep_seconds": 30}, lambda e: None, timeout=60.0, cancel_check=lambda: True)
    elapsed = time.monotonic() - started
    assert elapsed < 10
