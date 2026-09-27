"""Market analyst whose numbers come from code, not from the model.

The upstream market analyst is an LLM that is *asked* to call the indicator tools.
A small local model often does not: it answers straight away and writes exact
RSI/MACD/SMA values from memory, which nothing ever computed. Here the numbers are
computed unconditionally (``build_verified_market_snapshot`` — latest OHLCV, 11
indicators, recent closes; deterministic, no LLM) and the model only *writes the
report* about them, in a single plain call with no tools. That also removes the
open-ended tool-calling loop that small models can get stuck in.

If the snapshot cannot be built, the original analyst runs instead, so a data
failure degrades to the old behaviour rather than to an empty report.
"""
from __future__ import annotations

import time
from typing import Any, Callable

SYSTEM_PROMPT = """You are a technical market analyst writing for traders.

You are given a VERIFIED market data snapshot for one instrument, computed by code from real market data: the latest OHLCV row, technical indicators and recent closes. Write a detailed, nuanced technical report on trend, momentum, volatility and price levels.

Strict rules:
- Every number you cite MUST appear in the snapshot. Do not calculate, estimate or recall any other value (no other indicators, no averages of your own, no percentages that are not literally in the snapshot).
- You may describe relationships between snapshot values (price above or below a moving average, MACD above or below its signal, RSI in a zone, price near a Bollinger band).
- If something you would like to discuss is not in the snapshot, say that the data is not available. Do not invent it.
- Do not claim historical validation, past support/resistance bounces or exact price targets.
- State plainly when signals conflict; do not force a conclusion.

End the report with a Markdown table that organizes the key points."""


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content).strip()
    return str(content or "").strip()


def make_grounded_market_analyst(
    original_factory: Callable[[Any], Callable],
    emit: Callable[[str, str], None],
    build_snapshot: Callable[..., str],
    instrument_context: Callable[[dict], str],
    language_instruction: Callable[[], str],
    look_back_days: int = 30,
) -> Callable[[Any], Callable]:
    """Return a drop-in replacement for ``create_market_analyst``."""

    def create(llm):
        fallback = original_factory(llm)

        def market_analyst_node(state):
            ticker, trade_date = state["company_of_interest"], state["trade_date"]
            emit("tool_request", f"Cálculo obrigatório dos indicadores: get_verified_market_snapshot({ticker}, {trade_date}, {look_back_days})")
            started = time.perf_counter()
            try:
                snapshot = build_snapshot(ticker, trade_date, look_back_days)
            except Exception as exc:  # noqa: BLE001 - any data failure falls back to the original analyst
                emit("tool_error", f"get_verified_market_snapshot falhou: {type(exc).__name__}: {exc} — usando o analista original")
                return fallback(state)
            flat = " ".join(snapshot.split())
            emit("tool_response", f"get_verified_market_snapshot respondeu em {time.perf_counter() - started:.2f}s · {flat[:900]}{'...' if len(flat) > 900 else ''}")

            messages = [
                ("system", SYSTEM_PROMPT + "\n\n" + language_instruction()),
                ("human", f"{instrument_context(state)}\n\nAnalysis date: {trade_date}\n\n{snapshot}"),
            ]
            report = _text(llm.invoke(messages).content)
            if not report:
                emit("tool_error", "O modelo não escreveu o relatório de mercado — usando o analista original")
                return fallback(state)
            from langchain_core.messages import AIMessage

            return {"messages": [AIMessage(content=report)], "market_report": report}

        return market_analyst_node

    return create
