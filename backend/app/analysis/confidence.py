"""How much can the analysis be trusted? A score from objective checks, not from the model.

A small local model asked "how confident are you?" just invents a number. This
module instead audits what the run actually did and wrote, using only the run's
own events (tool responses/errors, warnings, the per-stage texts) plus the real
closing price. Every point lost comes with a reason.

The score says how well-grounded the READING is (data arrived, report complete,
cited prices match the market, stages agree). It is NOT the probability that the
price goes up or down.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

PRICE_CAP = 60  # ceiling when half or more of the cited price levels are nowhere near the real market

CAVEAT = (
    "Mede o quanto a leitura está bem fundamentada em dados verificáveis. "
    "Não é a probabilidade de a ação subir ou cair."
)

_INDICATOR = re.compile(r"(rsi|macd|sma|ema|atr|vwma|bollinger|boll)[^\d\n]{0,45}-?\d+[.,]\d+", re.I)
_UNFINISHED = re.compile(r"would you like me to|shall i proceed|deseja que eu (prossiga|continue)|quer que eu (prossiga|continue)", re.I)
_LEVEL = re.compile(
    r"(stop[- ]?loss|stop|alvo|target|price target|preço[- ]alvo|entrada|entry(?: price)?)"
    r"\D{0,30}?(?:R\$\s*)?(\d{1,3}(?:[.,]\d{1,3})?)(?!\s*%|\d)",
    re.I,
)
_DIRECTION = {"buy": 1, "overweight": 1, "hold": 0, "underweight": -1, "sell": -1}
_NO_DATA = re.compile(r"no news found|unavailable|data_unavailable|no market data|error retrieving|not found|nenhuma informa", re.I)


def _stages(events: list[dict]) -> dict[int, dict[str, str | None]]:
    out: dict[int, dict[str, str | None]] = {}
    for event in events:
        if event.get("kind") != "stage":
            continue
        text = event.get("text", "")
        m = re.match(r"^(\d)\. [^→·]*?(?: → ([^·]+?))? · (.*)$", text, re.S)
        if m:
            out[int(m.group(1))] = {"rating": (m.group(2) or "").strip() or None, "body": m.group(3)}
    return out


def _tool_texts(events: list[dict], name: str) -> list[str]:
    tag = f"{name} respondeu"
    return [e.get("text", "") for e in events if e.get("kind") == "tool_response" and tag in e.get("text", "")]


def _indicator_data(events: list[dict]) -> bool:
    """Indicators were computed by code: the indicator tool or the mandatory verified snapshot."""
    return _has_data(_tool_texts(events, "get_indicators")) or _has_data(_tool_texts(events, "get_verified_market_snapshot"))


def _has_data(texts: list[str]) -> bool:
    return any(t and not _NO_DATA.search(t.split("·", 1)[-1][:400]) for t in texts)


def _num(value: str) -> float | None:
    value = value.strip()
    try:
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", ".")
        return float(value)
    except ValueError:
        return None


def _check(cid: str, label: str, weight: int, score: float | None, reason: str, items: list[str] | None = None) -> dict[str, Any]:
    status = "n/a" if score is None else "ok" if score >= 0.999 else "falhou" if score <= 0.001 else "parcial"
    check = {"id": cid, "label": label, "weight": weight, "score": score, "status": status, "reason": reason}
    if items:
        check["items"] = items
    return check


def _numbers_audit(events) -> dict:
    """Share of the numbers written by the model that the run's real sources back up."""
    label = "Números do texto conferem com as fontes"
    audit = None
    for event in events:
        if event.get("kind") == "numbers_audit":
            try:
                audit = json.loads(event.get("text", ""))
            except (json.JSONDecodeError, TypeError):
                audit = None
    if audit is None:
        return _check("numeros", label, 15, None, "Auditoria de números não registrada nesta execução (anterior a este recurso).")
    total = audit.get("total", 0)
    if not total:
        return _check("numeros", label, 15, None, "O texto não traz números verificáveis.")
    backed = audit.get("verified", 0) + audit.get("derived", 0)
    items = []
    for stage in audit.get("stages", []):
        short = re.sub(r"^\d+\.\s*", "", stage["stage"]).split(" (")[0]
        for m in stage.get("missing", []):
            items.append(f"{m['raw']} — {short}: “…{m['context']}…”")
    extra = f" ({audit.get('derived', 0)} são contas simples sobre os dados)" if audit.get("derived") else ""
    reason = f"{backed} de {total} números conferem com o que as ferramentas retornaram{extra}."
    if audit.get("unverified"):
        reason += f" {audit['unverified']} sem fonte (não prova que estejam errados; a análise não consegue comprová-los)."
    return _check("numeros", label, 15, backed / total, reason, items[:12])


def _market_report(stages, events) -> dict:
    if not stages:
        # Runs from before per-stage capture never stored the report texts; that is a
        # gap in what was recorded, not a failure of the analysis itself.
        return _check("mercado", "Relatório técnico completo", 20, None, "Execução anterior ao registro das etapas: texto do relatório não foi guardado.")
    body = (stages.get(1) or {}).get("body") or ""
    if not body.strip():
        return _check("mercado", "Relatório técnico completo", 20, 0.0, "O relatório do analista de mercado não foi produzido.")
    if _UNFINISHED.search(body):
        return _check("mercado", "Relatório técnico completo", 20, 0.0, "O relatório termina pedindo permissão para continuar: a análise técnica não foi feita.")
    found = len({m.group(1).lower() for m in _INDICATOR.finditer(body)})
    if found >= 3:
        if not _indicator_data(events):
            # The numbers in the report did not come from any indicator tool: the model
            # either computed them itself or made them up, so they cannot be trusted.
            return _check(
                "mercado", "Relatório técnico completo", 20, 0.4,
                f"Cita valores de {found} indicadores, mas nenhuma ferramenta de indicadores retornou dados: os números não foram calculados pelo sistema.",
            )
        return _check("mercado", "Relatório técnico completo", 20, 1.0, f"Cita valores de {found} indicadores técnicos, calculados pela ferramenta.")
    return _check("mercado", "Relatório técnico completo", 20, 0.5 if found else 0.0, f"Só {found} indicador(es) com valor numérico no relatório.")


def _data_arrived(events) -> dict:
    news_ok = _has_data(_tool_texts(events, "get_news")) or any(
        e.get("kind") == "sentiment_response" and "Google News (pt-BR)" in e.get("text", "") and "headlines about" in e.get("text", "")
        for e in events
    )
    sources = {
        "preços": _has_data(_tool_texts(events, "get_stock_data")) or _has_data(_tool_texts(events, "get_verified_market_snapshot")),
        "indicadores": _indicator_data(events),
        "balanços": any(_has_data(_tool_texts(events, n)) for n in ("get_balance_sheet", "get_income_statement", "get_cashflow")),
        "notícias": news_ok,
    }
    missing = [name for name, ok in sources.items() if not ok]
    score = (len(sources) - len(missing)) / len(sources)
    reason = "Todas as fontes de dados responderam." if not missing else f"Sem dados de: {', '.join(missing)}."
    return _check("dados", "Fontes de dados responderam", 15, score, reason)


def _sentiment(events, stages) -> dict:
    body = (stages.get(2) or {}).get("body")
    if body is None:
        return _check("sentimento", "Sentimento baseado em dados", 15, None, "Analista de sentimento não rodou.")
    no_headlines = any(
        e.get("kind") == "sentiment_response" and re.search(r"<no Google News|Google News unavailable", e.get("text", ""))
        for e in events
    )
    says_empty = bool(re.search(r"nenhuma informa[cç][aã]o foi encontrada|no news (were )?found|silêncio|silence", body, re.I))
    if no_headlines or (says_empty and not _has_data(_tool_texts(events, "get_news"))):
        return _check("sentimento", "Sentimento baseado em dados", 15, 0.0, "O relatório de sentimento foi escrito sem notícias no período.")
    if re.search(r"confidence:?\**\s*low", body, re.I):
        return _check("sentimento", "Sentimento baseado em dados", 15, 0.5, "O próprio relatório declara confiança baixa.")
    return _check("sentimento", "Sentimento baseado em dados", 15, 1.0, "Sentimento construído sobre notícias reais do período.")


def _price_levels(stages, reference_close) -> dict:
    if not reference_close:
        return _check("precos", "Preços citados batem com o mercado", 15, None, "Preço de referência indisponível para conferir.")
    levels = []
    for n in (6, 7, 9):
        for m in _LEVEL.finditer((stages.get(n) or {}).get("body") or ""):
            value = _num(m.group(2))
            if value is not None and value > 3:  # ignore "target 1", counts, years-as-months, etc.
                levels.append((m.group(1).lower(), value))
    if not levels:
        return _check("precos", "Preços citados batem com o mercado", 15, None, "Nenhum preço de stop/alvo/entrada foi citado.")
    good = [(k, v) for k, v in levels if 0.6 * reference_close <= v <= 1.6 * reference_close]
    bad = [(k, v) for k, v in levels if (k, v) not in good]
    score = len(good) / len(levels)
    if not bad:
        return _check("precos", "Preços citados batem com o mercado", 15, 1.0, f"{len(levels)} nível(is) de preço citado(s), todos próximos do fechamento real (R$ {reference_close:.2f}).")
    sample = ", ".join(f"{k} R$ {v:.2f}" for k, v in bad[:3])
    return _check("precos", "Preços citados batem com o mercado", 15, score, f"Preço fora da realidade (fechamento real R$ {reference_close:.2f}): {sample}.")


def _agreement(stages) -> dict:
    dirs = [_DIRECTION[r.lower()] for n in (6, 7, 9) if (r := (stages.get(n) or {}).get("rating")) and r.lower() in _DIRECTION]
    if len(dirs) < 2:
        return _check("acordo", "Etapas de decisão concordam", 10, None, "Menos de duas etapas com rating reconhecido.")
    spread = max(dirs) - min(dirs)
    if spread == 0:
        return _check("acordo", "Etapas de decisão concordam", 10, 1.0, "Research Manager, Trader e Portfolio Manager apontam a mesma direção.")
    if spread == 1:
        return _check("acordo", "Etapas de decisão concordam", 10, 0.5, "As etapas divergem por um nível (ex.: Hold contra Buy).")
    return _check("acordo", "Etapas de decisão concordam", 10, 0.0, "As etapas de decisão apontam direções opostas.")


def _structure(events) -> dict:
    fails = sum(1 for e in events if e.get("kind") == "warning" and "structured-output" in e.get("text", ""))
    score = {0: 1.0, 1: 0.6, 2: 0.3}.get(fails, 0.0)
    reason = "Nenhuma falha de saída estruturada." if not fails else f"{fails} etapa(s) falharam em gerar saída estruturada e usaram texto livre."
    return _check("estrutura", "Respostas no formato esperado", 10, score, reason)


def _fresh_fundamentals(events, trade_date: str) -> dict:
    texts = _tool_texts(events, "get_balance_sheet")
    period = None
    for t in texts:
        m = re.search(r"Data retrieved on: [\d\- :]+\s*,(\d{4}-\d{2}-\d{2})", t)
        if m:
            period = m.group(1)
            break
    if not period:
        return _check("frescor", "Balanço recente", 10, None, "Data do último balanço não identificada.")
    try:
        age = (datetime.strptime(trade_date[:10], "%Y-%m-%d").date() - datetime.strptime(period, "%Y-%m-%d").date()).days
    except ValueError:
        return _check("frescor", "Balanço recente", 10, None, "Data do balanço ilegível.")
    # An annual statement is only published once a year, so it is naturally older than a
    # quarterly one; judge each against its own cadence.
    annual = any("(annual)" in t for t in texts)
    fresh, stale = (460, 800) if annual else (200, 400)
    kind = "anual" if annual else "trimestral"
    if age <= fresh:
        return _check("frescor", "Balanço recente", 10, 1.0, f"Último balanço {kind} de {period} ({age} dias antes da análise).")
    if age <= stale:
        return _check("frescor", "Balanço recente", 10, 0.5, f"Último balanço {kind} de {period} ({age} dias antes): defasado.")
    return _check("frescor", "Balanço recente", 10, 0.0, f"Último balanço {kind} de {period} ({age} dias antes): muito antigo.")


def _tool_errors(events) -> dict:
    n = sum(1 for e in events if e.get("kind") == "tool_error")
    score = max(0.0, 1 - 0.25 * n)
    return _check("erros", "Ferramentas sem erro", 5, score, "Nenhuma ferramenta falhou." if not n else f"{n} chamada(s) de ferramenta falharam.")


def assess_confidence(events: list[dict], trade_date: str, reference_close: float | None = None) -> dict[str, Any]:
    """Score (0-100) with the per-check breakdown, from a run's own events."""
    stages = _stages(events)
    checks = [
        _market_report(stages, events),
        _data_arrived(events),
        _sentiment(events, stages),
        _price_levels(stages, reference_close),
        _numbers_audit(events),
        _agreement(stages),
        _structure(events),
        _fresh_fundamentals(events, trade_date),
        _tool_errors(events),
    ]
    applicable = [c for c in checks if c["score"] is not None]
    total = sum(c["weight"] for c in applicable)
    pct = round(100 * sum(c["weight"] * c["score"] for c in applicable) / total) if total else None
    cap = None
    prices = next((c for c in checks if c["id"] == "precos"), None)
    if pct is not None and prices and prices["score"] is not None and prices["score"] <= 0.5 and pct > PRICE_CAP:
        # A decision built on price levels far from the real market is not made trustworthy by
        # everything else being fine: it caps the whole score (seen live: Buy with a R$ 200 stop
        # and a R$ 4 entry on a R$ 41 stock scored 84%).
        cap = {"limit": PRICE_CAP, "reason": "Preços de stop/entrada/alvo muito distantes do mercado real limitam a nota."}
        pct = PRICE_CAP
    label = None if pct is None else "Alta" if pct >= 75 else "Média" if pct >= 50 else "Baixa"
    # Share of the criteria that could actually be evaluated for this run. A 100% built
    # on 3 of 8 checks (old runs did not record the stage texts) must not read as a full audit.
    coverage = round(100 * total / sum(c["weight"] for c in checks))
    return {"pct": pct, "label": label, "coverage": coverage, "cap": cap, "checks": checks, "caveat": CAVEAT}
