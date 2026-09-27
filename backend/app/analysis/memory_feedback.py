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

# Seen live: a Hold on PETR4 2026-08-17 (missed a real +22.5% rally) was
# reflected on as "the directional call was correct, as the +10.6% alpha ...
# exceeded the benchmark" — backwards. raw_return/alpha_return are the
# STOCK's buy-and-hold return, independent of what the decision actually
# was; upstream's prompt hands the model that figure and asks "was the
# directional call correct" without ever stating that link, so a Hold that
# forfeited a big move gets scored as a win whenever the move happened to be
# positive. Patched in place (matches worker.py's other ``_install_*``
# monkeypatches) rather than editing the vendored file.
_FIXED_REFLECTION_PROMPT = (
    "You are a trading analyst reviewing your own past decision now that the outcome is known.\n"
    "IMPORTANT: raw_return/alpha_return are the STOCK's buy-and-hold return over the holding "
    "period — not what your decision itself earned. Judge correctness against the RATING you "
    "actually gave, using this rule:\n"
    "- Buy/Overweight is validated by a positive alpha, and failed by a negative one.\n"
    "- Sell/Underweight is validated by a negative alpha, and failed by a positive one.\n"
    "- Hold is a bet that nothing decisive would happen: it is validated only when |alpha| stayed "
    "small, and it FAILED — forfeiting a real move it could have captured or avoided — whenever "
    "|alpha| turned out large in either direction, even though Hold itself neither gained nor lost "
    "anything directly.\n\n"
    "Write exactly 2-4 sentences of plain prose (no bullets, no headers, no markdown).\n\n"
    "Cover in order:\n"
    "1. Which rating was actually given, and was it validated or did it fail by the rule above? "
    "(cite the alpha figure)\n"
    "2. Which part of the investment thesis held or failed?\n"
    "3. One concrete lesson to apply to the next similar analysis.\n\n"
    "Be specific and terse. Your output will be stored verbatim in a decision log "
    "and re-read by future analysts, so every word must earn its place."
)


def install_fixed_reflection_prompt() -> None:
    """Idempotent: reassigns the same lambda every call, safe to call from
    both this module and worker.py without caring which ran first."""
    from tradingagents.graph.reflection import Reflector

    Reflector._get_log_reflection_prompt = lambda self: _FIXED_REFLECTION_PROMPT


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

        install_fixed_reflection_prompt()
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
