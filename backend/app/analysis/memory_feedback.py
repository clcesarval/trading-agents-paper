"""Closes the loop that upstream's decision memory leaves half-open.

``TradingAgentsGraph.propagate`` already writes a "pending" entry for every
decision (Phase A — see ``tradingagents.agents.utils.memory.TradingMemoryLog
.store_decision``), and the Portfolio Manager prompt already promises
"Lessons from prior decisions and outcomes" (``get_past_context``). But
``get_past_context`` only ever returns *resolved* entries, and nothing in
this backend ever called Phase B (``update_with_outcome``) to fill one in —
so in practice that lessons line was always empty. Every run "learned"
nothing from the ones before it, including the exact case that motivated
this: a Hold that missed a real +22% rally, with no way for a later run on
the same ticker to be told so.

This module is that missing Phase B: once a date's real return is known
(backtest resolution, or a live analysis old enough to have one), generate a
short reflection with upstream's own ``Reflector`` and write it into the same
``memory.md`` file future runs already read from.
"""
from __future__ import annotations

import logging

from ..config import settings

logger = logging.getLogger(__name__)

# Must equal the ``memory_log_path`` every run is launched with (adapter.py /
# worker.py) — same fixed file for every ticker/date, by design (that's the
# whole point: later runs, of any ticker, read everything written before them).
MEMORY_LOG_PATH = "data/tradingagents/memory.md"


def record_outcome(
    *,
    ticker: str,
    trade_date: str,
    final_decision: str | None,
    raw_return: float | None,
    alpha_return: float | None,
    holding_days: int | None,
    resolution_date: str | None,
    benchmark: str | None,
    model: str | None,
) -> bool:
    """Write the real outcome, plus a generated reflection, into the shared
    memory log. Returns whether it actually wrote something.

    Never raises: a reflection is a nice-to-have on top of an already-complete
    backtest date, so any failure here (Ollama unreachable, malformed decision
    text, ...) is logged and swallowed rather than surfaced as an error on
    work that already succeeded.
    """
    if not final_decision or raw_return is None or alpha_return is None or not model:
        return False
    try:
        from tradingagents.agents.utils.memory import TradingMemoryLog
        from tradingagents.graph.reflection import Reflector
        from tradingagents.llm_clients import create_llm_client

        llm = create_llm_client(
            provider="ollama",
            model=model,
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            temperature=settings.llm_temperature,
        ).get_llm()
        reflection = Reflector(llm).reflect_on_final_decision(
            final_decision, raw_return, alpha_return, benchmark_name=benchmark or "^BVSP",
        )
        TradingMemoryLog({"memory_log_path": MEMORY_LOG_PATH}).update_with_outcome(
            ticker=ticker,
            trade_date=trade_date,
            raw_return=raw_return,
            alpha_return=alpha_return,
            holding_days=holding_days or 0,
            reflection=reflection,
            resolution_date=resolution_date,
        )
        return True
    except Exception:
        logger.exception("memory_feedback.record_outcome falhou para %s %s", ticker, trade_date)
        return False
