"""Cross-run consensus for one trade date.

Research on LLM trading agents (FINSABER, TradeTrap and related surveys) finds
that a single run's verbal confidence barely predicts whether its decision is
actually reliable — the same date can flip between Buy and Hold across
independent runs (seen live: PETR4 2026-08-17 came back Buy, Hold, Hold and
Buy across four attempts). Re-running the decision and checking whether
independent attempts *agree* is a stronger signal than trusting whichever
attempt happened to run once.

This module takes several full-pipeline attempts for the same date and turns
them into one verdict, instead of reporting whichever attempt finished.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

REVIEW = "REVIEW"  # an attempt that came back INCONCLUSIVE (no rating extracted)


def summarize_consensus(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """``attempts``: one dict per pipeline run, each with ``decision``
    ("BUY"/"HOLD"/"SELL"/None) and ``confidence_pct`` (int/float/None).
    ``None`` decision means that attempt came back INCONCLUSIVE — it counts
    as its own outcome, never as a silent vote for anything else.

    The reported decision is the strict majority (more than half of the
    attempts) among the non-REVIEW votes. A split (e.g. 1 Buy / 1 Hold / 1
    Sell) or a tie reports ``decision: None`` with the vote breakdown, so the
    caller can say "sem consenso" instead of picking one arbitrarily.
    """
    n = len(attempts)
    if n == 0:
        return {"runs": 0, "votes": {}, "decision": None, "agreement": 0.0, "confidence_pct": None, "note": "Nenhuma execução registrada."}

    labels = [a.get("decision") or REVIEW for a in attempts]
    votes = Counter(labels)
    decided = n - votes.get(REVIEW, 0)
    winner, top_count = votes.most_common(1)[0]
    has_majority = winner != REVIEW and decided > 0 and top_count > decided / 2
    agreement = round(top_count / n, 2)

    confidences = [
        a.get("confidence_pct") for a in attempts
        if a.get("decision") == winner and a.get("confidence_pct") is not None
    ]
    avg_confidence = round(sum(confidences) / len(confidences)) if confidences else None

    votes_readable = ", ".join(f"{label}: {count}" for label, count in votes.most_common())
    note = (
        f"Consenso: {winner} em {top_count} de {n} execuções ({votes_readable})."
        if has_majority
        else f"Sem consenso entre {n} execuções ({votes_readable}) — decisões divergentes, resultado não é confiável."
    )
    return {
        "runs": n,
        "votes": dict(votes),
        "decision": winner if has_majority else None,
        "agreement": agreement,
        "confidence_pct": avg_confidence if has_majority else None,
        "note": note,
    }
