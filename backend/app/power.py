"""Keep Windows from sleeping while an analysis or backtest is running.

A backtest takes hours; Windows' idle timer (15 min by default) does not care that
a program is busy and would suspend the machine, freezing Ollama and the run.
While at least one holder is active we ask for ES_SYSTEM_REQUIRED (no sleep /
hibernate on idle). The display is not requested, so the screen may still turn
off. The request is per-thread and dies with the process, so a crashed or
reloaded server can never leave the PC unable to sleep. No-op off Windows.
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

_lock = threading.Lock()
_holders = 0


def _set_execution_state(flags: int) -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def acquire() -> None:
    global _holders
    with _lock:
        _holders += 1
        _set_execution_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def release() -> None:
    global _holders
    with _lock:
        _holders = max(0, _holders - 1)
        if _holders == 0:
            _set_execution_state(_ES_CONTINUOUS)


def active_holders() -> int:
    return _holders


@contextmanager
def keep_awake():
    acquire()
    try:
        yield
    finally:
        release()
