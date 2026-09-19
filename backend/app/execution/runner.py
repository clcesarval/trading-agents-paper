"""Drives one isolated analysis process from the FastAPI (asyncio) side.

The child process (``worker.run_worker``) can be genuinely killed on timeout
via ``Process.terminate()``/``kill()`` — unlike ``asyncio.to_thread``, which
leaves a thread running forever inside a blocking upstream call. Only one
of these should ever be in flight at a time (enforced by the caller's lock),
since both live analysis and each backtest date share the same local
Ollama/GPU slot.
"""
from __future__ import annotations

import multiprocessing
import queue as queue_mod
import time
from typing import Any, Callable

from .worker import run_worker

_CTX = multiprocessing.get_context("spawn")


class AnalysisTimeout(RuntimeError):
    pass


class AnalysisFailed(RuntimeError):
    def __init__(self, message: str, traceback_text: str | None = None):
        super().__init__(message)
        self.traceback_text = traceback_text


async def run_isolated(payload: dict[str, Any], on_event: Callable[[dict], None], timeout: float, on_start: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Run ``run_worker`` in a child process; return its result dict or raise.

    ``on_event`` is called (from a background thread, not the event loop) for
    every event the child emits, in near real time. ``on_start`` is called
    once with the child PID right after it launches, so the caller can
    persist it for the startup orphan sweep (``db.reconcile_orphan_runs``) —
    if this coroutine itself gets killed (e.g. uvicorn --reload) before it
    reaches its own timeout/cleanup logic, the recorded PID is the only way
    to find and kill the orphaned child later.
    """
    import asyncio

    q = _CTX.Queue()
    proc = _CTX.Process(target=run_worker, args=(payload, q), daemon=True)
    proc.start()
    if on_start:
        on_start(proc.pid)
    deadline = time.monotonic() + timeout
    outcome: dict[str, Any] = {}

    def drain() -> str:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            try:
                item = q.get(timeout=min(remaining, 0.5))
            except queue_mod.Empty:
                continue
            kind = item.get("kind")
            if kind == "__done__":
                return "finished"
            if kind in ("result", "error"):
                outcome["final"] = item
                continue
            on_event(item)

    outcome_kind = await asyncio.to_thread(drain)

    if outcome_kind == "timeout":
        proc.terminate()
        await asyncio.to_thread(proc.join, 5)
        if proc.is_alive():
            proc.kill()
            await asyncio.to_thread(proc.join, 5)
        raise AnalysisTimeout(
            f"Análise interrompida após {timeout:.0f}s; o processo de execução foi encerrado."
        )

    await asyncio.to_thread(proc.join, 5)
    final = outcome.get("final")
    if final is None:
        code = proc.exitcode
        raise AnalysisFailed(f"Processo de análise encerrou inesperadamente (código {code}) sem devolver resultado.")
    if final.get("kind") == "error":
        raise AnalysisFailed(final.get("error", "Falha desconhecida no processo de análise"), final.get("traceback"))
    return final
