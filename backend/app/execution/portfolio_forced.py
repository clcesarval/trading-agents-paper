"""Catches a Portfolio Manager decision that contradicts its own action plan,
and gives it one chance to fix itself before it reaches the trader as gospel.

Seen live: PETR4 2026-08-17, all 3 consensus attempts. Research Manager said
Buy, the Trader said Buy ("FINAL TRANSACTION PROPOSAL: **BUY**"), and the
Portfolio Manager's own Executive Summary read "Posicione-se comprando
PETR4.SA..." — yet it stamped **Rating: Hold**. Upstream's schema tells the
model when to *choose* Hold (balanced/conflicting/ambiguous evidence) but
never checks that the ``rating`` it picks matches what its own
``executive_summary`` actually describes doing — the two fields are filled
independently and can disagree with each other.

This wraps the real factory (100% of upstream's structured-output plumbing,
schema and state wiring stays untouched) and only intervenes when the
rendered decision is self-contradictory: same detect-then-retry shape as
``market_forced.py``'s grounded market analyst.
"""
from __future__ import annotations

import re
from typing import Any, Callable

_RATING_RE = re.compile(r"\*\*Rating\*\*:\s*([A-Za-z]+)")
_SUMMARY_RE = re.compile(r"\*\*Executive Summary\*\*:\s*(.+?)(?:\n\n\*\*|\Z)", re.DOTALL)

# Deliberately narrow: an unhedged, imperative opening ("Posicione-se
# comprando...", "Compre...", "Buy...") is what actually contradicts a
# neutral/opposite rating. A hedged one ("considere comprar se confirmar a
# ruptura") is not a commitment and must NOT trigger this — false positives
# here would flag perfectly reasonable cautious language as "contradictory".
_BUY_OPEN_RE = re.compile(
    r"^(posicione-se\s+comprando|compre\b|buy\b|adicione(?:\s+(?:a\s+)?posi[cç][aã]o)?\b|"
    r"aumente\s+(?:a\s+)?exposi[cç][aã]o|entre\s+na\s+posi[cç][aã]o)",
    re.IGNORECASE,
)
_SELL_OPEN_RE = re.compile(
    r"^(posicione-se\s+vendendo|venda\b|sell\b|reduza(?:\s+(?:a\s+)?posi[cç][aã]o)?\b|"
    r"encerre\s+(?:a\s+)?posi[cç][aã]o|saia\s+da\s+posi[cç][aã]o)",
    re.IGNORECASE,
)

_BULLISH_RATINGS = {"buy", "overweight"}
_BEARISH_RATINGS = {"underweight", "sell"}


def detect_rating_mismatch(decision_text: str) -> dict[str, str] | None:
    """None when the rendered decision is consistent (or unparseable — never
    flag what we can't actually read); otherwise the mismatch details."""
    rating_match = _RATING_RE.search(decision_text or "")
    summary_match = _SUMMARY_RE.search(decision_text or "")
    if not rating_match or not summary_match:
        return None
    rating = rating_match.group(1)
    summary = summary_match.group(1).strip()
    rating_lower = rating.lower()
    if _BUY_OPEN_RE.match(summary) and rating_lower not in _BULLISH_RATINGS:
        return {"rating": rating, "direction": "compra", "snippet": summary[:120]}
    if _SELL_OPEN_RE.match(summary) and rating_lower not in _BEARISH_RATINGS:
        return {"rating": rating, "direction": "venda", "snippet": summary[:120]}
    return None


def _correction_note(mismatch: dict[str, str]) -> str:
    return (
        "\n\nNOTA DO SISTEMA: sua última decisão se contradisse — o Rating "
        f"'{mismatch['rating']}' não bate com a ação de {mismatch['direction']} que o próprio "
        f"Executive Summary descrevia (\"{mismatch['snippet']}...\"). Escolha um Rating que "
        "reflita a direção do plano de ação que você mesmo descrever, ou reescreva o plano "
        "para não sugerir uma ação que o Rating escolhido contradiz."
    )


def make_consistent_portfolio_manager(original_factory: Callable, emit: Callable[[str, str], None]) -> Callable:
    """Wrap ``create_portfolio_manager`` so a self-contradictory decision gets
    exactly one retry, with the contradiction spelled out, before it stands."""

    def factory(llm) -> Callable[[dict], dict]:
        original_node = original_factory(llm)

        def node(state: dict) -> dict:
            result = original_node(state)
            mismatch = detect_rating_mismatch(result.get("final_trade_decision", ""))
            if mismatch is None:
                return result

            emit(
                "warning",
                f"Portfolio Manager: Rating '{mismatch['rating']}' contradiz o próprio "
                f"Executive Summary (ação de {mismatch['direction']}: \"{mismatch['snippet']}...\"); "
                "pedindo uma revisão.",
            )
            revised_state = dict(state)
            risk_debate_state = dict(state.get("risk_debate_state", {}))
            risk_debate_state["history"] = risk_debate_state.get("history", "") + _correction_note(mismatch)
            revised_state["risk_debate_state"] = risk_debate_state

            retried = original_node(revised_state)
            if detect_rating_mismatch(retried.get("final_trade_decision", "")) is None:
                emit("config", "Portfolio Manager: revisão resolveu a contradição entre Rating e Executive Summary.")
                return retried
            emit(
                "warning",
                "Portfolio Manager: a contradição persistiu após a revisão; mantendo a decisão "
                "original com a inconsistência sinalizada.",
            )
            return result

        return node

    return factory
