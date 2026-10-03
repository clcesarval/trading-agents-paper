"""Catches a Portfolio Manager decision that contradicts itself or its own
very recent history, and gives it one chance to fix itself before it
reaches the trader as gospel.

Three distinct patterns caught here:

1. ``detect_rating_mismatch`` (PETR4 2026-08-17) — Research Manager and
   Trader said Buy ("FINAL TRANSACTION PROPOSAL: **BUY**"), and the
   Portfolio Manager's own Executive Summary read "Posicione-se comprando
   PETR4.SA..." — yet it stamped **Rating: Hold**. Upstream's schema tells
   the model when to *choose* Hold but never checks that the rating matches
   what its own executive_summary describes doing.

2. ``detect_ignored_catalyst`` (PETR4 2026-08-17) — after the catalyst-weight
   rule below was already in the prompt, the model literally wrote
   "catalisador confirmado"/"catalisador datado" in its own Investment
   Thesis and still picked Hold, in all 3 attempts — echoing the rule's
   vocabulary as a rationalization instead of following its conclusion.

3. ``detect_decision_reversal`` (PETR4, real backtest of Oct/2025) — Buy on
   2025-10-14, Hold the very next day, Sell two days after that, while the
   price kept climbing the whole time. No new dated/confirmed catalyst
   justified any of those reversals — it just flip-flopped. Unlike the
   other two, this one deliberately does NOT fire on every
   Portfolio-Manager-vs-Trader disagreement (overriding the Trader after
   the risk debate is the Portfolio Manager's legitimate job) — only on a
   full directional U-turn from what THIS SAME TICKER decided a few days
   ago, with nothing new cited to justify it.

All three wrap the real factory (100% of upstream's structured-output
plumbing, schema and state wiring stays untouched) and only intervene when
the rendered decision is self-contradictory: same detect-then-retry shape
as ``market_forced.py``'s grounded market analyst.
"""
from __future__ import annotations

import re
from datetime import datetime
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
_NON_BULLISH_RATINGS = {"hold", "underweight", "sell"}
_NON_BEARISH_RATINGS = {"hold", "buy", "overweight"}

_THESIS_RE = re.compile(r"\*\*Investment Thesis\*\*:\s*(.+?)(?:\n\n\*\*|\Z)", re.DOTALL)
# The model was seen (PETR4 2026-08-17, all 3 attempts, after the weight rule
# below was already in the prompt) literally writing "catalisador
# datado"/"catalisador confirmado" and then picking Hold anyway — echoing the
# rule's own vocabulary as a rationalization instead of following its
# conclusion. Narrow window (~120 chars after the phrase) so the bullish/
# bearish keyword must describe the catalyst itself, not some unrelated
# bullish word elsewhere in a long paragraph.
_CATALYST_MENTION_RE = re.compile(
    r"catalisador(?:es)?\s+(?:datados?|confirmados?)(?:\s+e\s+(?:datados?|confirmados?))?[^.]{0,120}",
    re.IGNORECASE,
)
_BULLISH_CATALYST_RE = re.compile(r"descoberta|alta\s+(?:no|do|de|dos)|aumento|crescimento|expans[aã]o|recorde", re.IGNORECASE)
_BEARISH_CATALYST_RE = re.compile(r"queda|corte|rebaixamento|redu[cç][aã]o|processo|multa|sanção|sanc[aã]o", re.IGNORECASE)

# General rule, not tied to any one ticker/date: seen live (PETR4 2026-08-17)
# a confirmed, dated catalyst (a real, verified oil discovery headline) was
# repeatedly out-weighed by generic, permanent structural risk (leverage,
# commodity-price volatility) that carried no new information of its own —
# the debate treated "the company has debt" as if it were just as strong a
# reason as a fresh, verified event, every single time. This note is injected
# into every Portfolio Manager call (not just the retry path) so the rule
# applies to every analysis, not this one case.
_CATALYST_WEIGHT_RULE = (
    "\n\nREGRA DE PESO ENTRE EVIDÊNCIAS: antes de escolher o Rating, identifique (1) qualquer "
    "catalisador datado e confirmado nos relatórios dos analistas — um fato novo, já ocorrido, "
    "com data (ex.: uma notícia real, um resultado trimestral, uma descoberta confirmada) — e "
    "(2) os contra-argumentos, classificando cada um como 'fato novo e datado' ou 'risco "
    "estrutural permanente' (ex.: alavancagem, volatilidade histórica de commodity, dependência "
    "macro genérica — coisas que já eram verdade antes e continuam sendo, sem novidade). Um risco "
    "estrutural permanente NÃO tem o mesmo peso que um catalisador datado e confirmado só porque "
    "ambos aparecem no debate — ele só deve pesar mais quando vier acompanhado de um fato novo "
    "próprio (ex.: rebaixamento de rating recente, vencimento de dívida próximo, notícia negativa "
    "datada). Se o catalisador identificado for datado/confirmado e todo contra-argumento for "
    "apenas risco estrutural permanente sem fato novo, o Rating deve seguir a direção do "
    "catalisador (Buy/Overweight se positivo, Sell/Underweight se negativo) em vez de Hold."
)

# Observado num backtest real (PETR4, fev-abr/2025, 50 pregões de queda
# confirmada, alpha chegando a -21% vs. Ibovespa): o Portfolio Manager nunca
# deu Sell/Underweight uma única vez nesse período — só Hold, ou (3 vezes)
# Buy/Overweight no meio do agravamento da queda. Não é um problema de
# redação da escala de rating (Buy e Sell são descritos com critérios
# simétricos) nem da ordem do debate de risco (também simétrica) — é uma
# hipótese de viés comportamental do modelo, não comprovada como a regra de
# peso acima (que corrigia uma contradição textual real). Por isso essa nota
# é deliberadamente simétrica em ambas as direções, não só um empurrão pra
# Sell: o objetivo é remover qualquer relutância equivalente nos dois
# sentidos, não enviesar o modelo pro lado contrário.
_DIRECTIONAL_SYMMETRY_RULE = (
    "\n\nLEMBRETE DE SIMETRIA: Buy/Overweight e Sell/Underweight têm exatamente o mesmo "
    "critério de evidência — nenhum dos dois exige um padrão mais alto que o outro. Se a "
    "evidência (técnica, fundamentalista ou de catalisador) apontar claramente para baixa, "
    "recomende Sell/Underweight com a mesma disposição com que recomendaria Buy/Overweight "
    "num cenário de alta equivalente; não troque uma conclusão bearish clara por Hold só "
    "por cautela."
)

# Below this many resolved decisions for the ticker, a frequency note would
# be noise dressed up as a pattern (a 2-of-3 split sounds dramatic but is
# not a signal) — skip it rather than mislead. Deliberately counts only
# *frequency* (how often each rating was used), never *accuracy* (whether
# it was right): an accuracy figure computed the way this project's own
# backtests are graded (alpha vs. a 20-trading-day horizon) is itself
# regime-dependent — e.g. "Hold accuracy 16%" during a confirmed multi-month
# trend was an artifact of measuring every Hold against a horizon longer
# than the trend took to reverse, not evidence that Hold was the wrong call
# on any single day — so feeding a derived accuracy number back into the
# prompt as if it were ground truth would risk teaching the same
# over-literal lesson this project already caught and corrected for in its
# own backtest write-ups (see docs/sample_track.md). Frequency alone carries
# no such interpretation baked in.
_MIN_RESOLVED_FOR_HISTORICAL_NOTE = 10


def format_historical_rating_note(rating_counts: dict[str, int]) -> str | None:
    """``rating_counts`` is ``{rating_5tier: count}`` for one ticker's own
    resolved history (``backend/app/storage/db.rating_distribution``) — raw
    counts, no accuracy judgment (see ``_MIN_RESOLVED_FOR_HISTORICAL_NOTE``
    for why). Returns ``None`` below the minimum sample size."""
    total = sum(rating_counts.values())
    if total < _MIN_RESOLVED_FOR_HISTORICAL_NOTE:
        return None
    bullish = sum(n for rating, n in rating_counts.items() if (rating or "").lower() in _BULLISH_RATINGS)
    bearish = sum(n for rating, n in rating_counts.items() if (rating or "").lower() in _BEARISH_RATINGS)
    hold = total - bullish - bearish
    pct = lambda n: round(100 * n / total)
    return (
        "\n\nNOTA HISTÓRICA: nas últimas "
        f"{total} decisões reais já resolvidas para este ativo, a distribuição de ratings foi "
        f"{pct(bullish)}% Buy/Overweight, {pct(bearish)}% Sell/Underweight, {pct(hold)}% Hold. "
        "Isso é só um registro de frequência passada, não uma meta a cumprir nem uma indicação "
        "de que algum lado 'está devendo' — decida pela evidência de hoje; use este número "
        "apenas para checar se uma relutância recorrente em algum lado está influenciando o "
        "julgamento sem uma razão concreta."
    )


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
        return {"kind": "action_mismatch", "rating": rating, "direction": "compra", "snippet": summary[:120]}
    if _SELL_OPEN_RE.match(summary) and rating_lower not in _BEARISH_RATINGS:
        return {"kind": "action_mismatch", "rating": rating, "direction": "venda", "snippet": summary[:120]}
    return None


def detect_ignored_catalyst(decision_text: str) -> dict[str, str] | None:
    """None unless the Investment Thesis names its own catalyst as
    'datado'/'confirmado' — the exact vocabulary the weight rule below
    injects — while the Rating still doesn't follow that catalyst's
    direction. Real case: PETR4 2026-08-17 named the oil discovery a
    'catalisador confirmado' in all 3 attempts and still picked Hold."""
    rating_match = _RATING_RE.search(decision_text or "")
    thesis_match = _THESIS_RE.search(decision_text or "")
    if not rating_match or not thesis_match:
        return None
    rating_lower = rating_match.group(1).lower()
    for mention in _CATALYST_MENTION_RE.finditer(thesis_match.group(1)):
        span = mention.group(0)
        if _BULLISH_CATALYST_RE.search(span) and rating_lower in _NON_BULLISH_RATINGS:
            return {"kind": "ignored_catalyst", "rating": rating_match.group(1), "expected": "Buy/Overweight", "snippet": span.strip()[:140]}
        if _BEARISH_CATALYST_RE.search(span) and rating_lower in _NON_BEARISH_RATINGS:
            return {"kind": "ignored_catalyst", "rating": rating_match.group(1), "expected": "Sell/Underweight", "snippet": span.strip()[:140]}
    return None


# How many calendar days back counts as "very recent" for this same ticker.
# Wide enough to catch the real case (1-2 days apart) without reaching back
# so far that ordinary, legitimate changes of view get flagged.
_REVERSAL_WINDOW_DAYS = 5


def detect_decision_reversal(memory_log: Any, ticker: str, trade_date: str, decision_text: str) -> dict[str, str] | None:
    """None unless this decision is a full directional U-turn (Buy/Overweight
    <-> Sell/Underweight — Hold is never itself flagged as "the reversal")
    from the SAME ticker's own most recent prior decision, within
    ``_REVERSAL_WINDOW_DAYS``, with no dated/confirmed catalyst cited to
    justify the change. ``memory_log`` is a ``TradingMemoryLog`` — reused
    as-is, not reimplemented, since it already tracks exactly this history.
    """
    rating_match = _RATING_RE.search(decision_text or "")
    if not rating_match:
        return None
    current_lower = rating_match.group(1).lower()
    current_bullish = current_lower in _BULLISH_RATINGS
    current_bearish = current_lower in _BEARISH_RATINGS
    if not (current_bullish or current_bearish):
        return None  # only Buy/Sell can BE "the reversal" — Hold never triggers this on its own

    try:
        current_date = datetime.strptime(trade_date, "%Y-%m-%d")
        entries = [e for e in memory_log.load_entries() if e.get("ticker") == ticker]
    except Exception:
        return None

    prior = None
    prior_date = None
    for entry in entries:
        try:
            entry_date = datetime.strptime(entry.get("date", ""), "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if entry_date < current_date and (prior_date is None or entry_date > prior_date):
            prior, prior_date = entry, entry_date
    if prior is None:
        return None

    days_between = (current_date - prior_date).days
    if days_between > _REVERSAL_WINDOW_DAYS:
        return None

    prior_lower = (prior.get("rating") or "").lower()
    prior_bullish = prior_lower in _BULLISH_RATINGS
    prior_bearish = prior_lower in _BEARISH_RATINGS
    if not ((current_bullish and prior_bearish) or (current_bearish and prior_bullish)):
        return None

    thesis_match = _THESIS_RE.search(decision_text or "")
    if thesis_match and _CATALYST_MENTION_RE.search(thesis_match.group(1)):
        return None  # a cited catalyst is an acceptable reason to reverse

    return {
        "kind": "decision_reversal",
        "rating": rating_match.group(1),
        "prior_rating": prior.get("rating") or "?",
        "prior_date": prior.get("date") or "?",
        "days_between": str(days_between),
    }


def _correction_note(mismatch: dict[str, str]) -> str:
    if mismatch["kind"] == "decision_reversal":
        return (
            f"\n\nNOTA DO SISTEMA: essa decisão ({mismatch['rating']}) reverte totalmente a "
            f"decisão de {mismatch['days_between']} dia(s) atrás para o mesmo ativo "
            f"({mismatch['prior_date']}: {mismatch['prior_rating']}), sem citar nenhum catalisador "
            "datado/confirmado que justifique a virada. Se não houver um fato novo real desde então, "
            "prefira uma direção mais próxima da decisão anterior (ex.: Hold em vez de reversão total); "
            "se houver um fato novo, cite-o explicitamente no Investment Thesis."
        )
    if mismatch["kind"] == "ignored_catalyst":
        return (
            "\n\nNOTA DO SISTEMA: você mesmo classificou um catalisador como datado/confirmado "
            f"(\"{mismatch['snippet']}...\") mas escolheu Rating '{mismatch['rating']}' — isso "
            f"contradiz a REGRA DE PESO ENTRE EVIDÊNCIAS: um catalisador datado/confirmado exige "
            f"Rating {mismatch['expected']}, a menos que exista um contra-argumento IGUALMENTE "
            "datado e confirmado (não apenas risco estrutural permanente). Se esse contra-argumento "
            "não existir, mude o Rating para seguir o catalisador; se existir, nomeie-o "
            "explicitamente no Investment Thesis."
        )
    return (
        "\n\nNOTA DO SISTEMA: sua última decisão se contradisse — o Rating "
        f"'{mismatch['rating']}' não bate com a ação de {mismatch['direction']} que o próprio "
        f"Executive Summary descrevia (\"{mismatch['snippet']}...\"). Escolha um Rating que "
        "reflita a direção do plano de ação que você mesmo descrever, ou reescreva o plano "
        "para não sugerir uma ação que o Rating escolhido contradiz."
    )


def _detect_any_issue(decision_text: str, *, memory_log: Any = None, ticker: str | None = None, trade_date: str | None = None) -> dict[str, str] | None:
    mismatch = detect_rating_mismatch(decision_text) or detect_ignored_catalyst(decision_text)
    if mismatch is not None:
        return mismatch
    if memory_log is not None and ticker and trade_date:
        return detect_decision_reversal(memory_log, ticker, trade_date, decision_text)
    return None


def make_consistent_portfolio_manager(
    original_factory: Callable,
    emit: Callable[[str, str], None],
    memory_log: Any = None,
    historical_rating_note: str | None = None,
) -> Callable:
    """Wrap ``create_portfolio_manager`` so a self-contradictory decision gets
    exactly one retry, with the contradiction spelled out, before it stands.

    ``memory_log`` (a ``TradingMemoryLog``) is optional — when given, also
    enables ``detect_decision_reversal`` against this ticker's own recent
    decisions; without it, only the two purely-textual checks run.

    ``historical_rating_note`` (from ``format_historical_rating_note``) is
    optional pre-formatted text — computed once in the main process (it needs
    the SQLite DB, which this child-process code must never open directly)
    and passed down through the job payload, same as the API keys are.
    """

    def factory(llm) -> Callable[[dict], dict]:
        original_node = original_factory(llm)

        def node(state: dict) -> dict:
            # Applied on every call, not just the retry path — a general rule,
            # not a patch for one date.
            weighted_state = dict(state)
            base_risk_debate_state = dict(state.get("risk_debate_state", {}))
            base_risk_debate_state["history"] = (
                base_risk_debate_state.get("history", "")
                + _CATALYST_WEIGHT_RULE
                + _DIRECTIONAL_SYMMETRY_RULE
                + (historical_rating_note or "")
            )
            weighted_state["risk_debate_state"] = base_risk_debate_state

            ticker = state.get("company_of_interest")
            trade_date = state.get("trade_date")

            result = original_node(weighted_state)
            mismatch = _detect_any_issue(result.get("final_trade_decision", ""), memory_log=memory_log, ticker=ticker, trade_date=trade_date)
            if mismatch is None:
                return result

            if mismatch["kind"] == "ignored_catalyst":
                emit(
                    "warning",
                    f"Portfolio Manager: nomeou um catalisador datado/confirmado (\"{mismatch['snippet']}...\") "
                    f"mas escolheu Rating '{mismatch['rating']}' em vez de {mismatch['expected']}; pedindo uma revisão.",
                )
            elif mismatch["kind"] == "decision_reversal":
                emit(
                    "warning",
                    f"Portfolio Manager: Rating '{mismatch['rating']}' reverte a decisão de "
                    f"{mismatch['days_between']} dia(s) atrás ({mismatch['prior_rating']}) sem catalisador novo citado; "
                    "pedindo uma revisão.",
                )
            else:
                emit(
                    "warning",
                    f"Portfolio Manager: Rating '{mismatch['rating']}' contradiz o próprio "
                    f"Executive Summary (ação de {mismatch['direction']}: \"{mismatch['snippet']}...\"); "
                    "pedindo uma revisão.",
                )
            revised_state = dict(weighted_state)
            risk_debate_state = dict(weighted_state.get("risk_debate_state", {}))
            risk_debate_state["history"] = risk_debate_state.get("history", "") + _correction_note(mismatch)
            revised_state["risk_debate_state"] = risk_debate_state

            retried = original_node(revised_state)
            if _detect_any_issue(retried.get("final_trade_decision", ""), memory_log=memory_log, ticker=ticker, trade_date=trade_date) is None:
                emit("config", "Portfolio Manager: revisão resolveu a inconsistência.")
                return retried
            emit(
                "warning",
                "Portfolio Manager: a inconsistência persistiu após a revisão; mantendo a decisão "
                "original com o problema sinalizado.",
            )
            return result

        return node

    return factory
