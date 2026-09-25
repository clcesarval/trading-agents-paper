import pytest

from backend.app import power


@pytest.fixture()
def flags(monkeypatch):
    calls = []
    monkeypatch.setattr(power, "_set_execution_state", calls.append)
    monkeypatch.setattr(power, "_holders", 0)
    return calls


def test_sleep_is_blocked_while_any_job_runs_and_released_after_the_last(flags):
    power.acquire()
    power.acquire()  # e.g. a live analysis overlapping a backtest date
    assert flags[-1] == power._ES_CONTINUOUS | power._ES_SYSTEM_REQUIRED
    power.release()
    assert power.active_holders() == 1
    assert flags[-1] == power._ES_CONTINUOUS | power._ES_SYSTEM_REQUIRED  # still one holder
    power.release()
    assert power.active_holders() == 0
    assert flags[-1] == power._ES_CONTINUOUS  # requirement cleared: PC may sleep again


def test_sleep_block_is_released_even_if_the_job_crashes(flags):
    with pytest.raises(RuntimeError):
        with power.keep_awake():
            raise RuntimeError("job exploded")
    assert power.active_holders() == 0
    assert flags[-1] == power._ES_CONTINUOUS


def test_display_is_never_requested(flags):
    with power.keep_awake():
        assert not (flags[-1] & 0x00000002)  # ES_DISPLAY_REQUIRED: the screen may still turn off
