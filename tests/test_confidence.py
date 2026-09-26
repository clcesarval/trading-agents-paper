from backend.app.analysis.confidence import assess_confidence


def _ev(kind, text):
    return {"kind": kind, "text": text}


def _good_events():
    return [
        _ev("tool_response", "get_stock_data respondeu em 0.5s · # Stock data for PETR4.SA Date,Open,High 2026-07-06,41.1"),
        _ev("tool_response", "get_indicators respondeu em 0.1s · ## rsi values from 2026-06-06 to 2026-07-06: 2026-07-06: 55.2"),
        _ev("tool_response", "get_balance_sheet respondeu em 0.8s · # Balance Sheet data for PETR4.SA (quarterly) # Data retrieved on: 2026-09-25 09:39:46 ,2026-03-31,2025-12-31 Treasury"),
        _ev("tool_response", "get_news respondeu em 0.7s · ## PETR4.SA News: Petrobras sobe com petróleo"),
        _ev("stage", "1. Analista de Mercado (relatório) · RSI 55.2 neutro, MACD -0.19 negativo, SMA50 44.23, ATR 1.31, VWMA 44.40, Bollinger 47.35."),
        _ev("stage", "2. Analista de Sentimento (relatório) · **Overall Sentiment:** **Neutral** (Score: 5/10) **Confidence:** Medium notícias reais."),
        _ev("stage", "6. Research Manager (plano de investimento) → Hold · Manter. Entrada perto de R$ 41,00 com stop R$ 38,50."),
        _ev("stage", "7. Trader (proposta de operação) → Hold · Manter."),
        _ev("stage", "9. Portfolio Manager (decisão final) → Hold · Sem ação."),
    ]


def test_well_grounded_analysis_scores_high_with_every_check_passing():
    result = assess_confidence(_good_events(), "2026-07-06", reference_close=41.18)
    assert result["pct"] >= 90 and result["label"] == "Alta"
    assert all(c["status"] in ("ok", "n/a") for c in result["checks"])
    assert "não é a probabilidade" in result["caveat"].lower()


def test_the_untrustworthy_buy_of_2026_08_17_scores_low_and_says_why():
    # Real case: market report never did the analysis, sentiment had no news, and the
    # model wrote a stop-loss of R$ 21.50 while PETR4 closed at R$ 41.18.
    events = [
        _ev("tool_response", "get_stock_data respondeu em 0.5s · # Stock data for PETR4.SA Date,Open 2026-08-14,40.8"),
        _ev("tool_response", "get_indicators respondeu em 0.1s · ## rsi values: 2026-08-17: 55.0"),
        _ev("tool_response", "get_balance_sheet respondeu em 0.8s · # Balance Sheet data # Data retrieved on: 2026-09-25 09:39:46 ,2025-12-31,2025-09-30"),
        _ev("sentiment_response", "Notícias pt-BR (Google News) respondeu em 1.2s · <no Google News headlines found for PETR4 between 2026-08-10 and 2026-08-17>"),
        _ev("stage", "1. Analista de Mercado (relatório) · Analysis Preparation: I can now analyze the trends. Would you like me to proceed with the full analysis using these data points?"),
        _ev("stage", "2. Analista de Sentimento (relatório) · **Overall Sentiment:** **Bullish** (Score: 7.0/10) **Confidence:** Low Nenhuma informação foi encontrada no período."),
        _ev("stage", "6. Research Manager (plano de investimento) → Buy · Comprar."),
        _ev("stage", "7. Trader (proposta de operação) → Buy · Comprar."),
        _ev("stage", "9. Portfolio Manager (decisão final) → Buy · Iniciar posição com stop-loss em R$ 21,50 e alvo em R$ 27,00."),
    ]
    result = assess_confidence(events, "2026-08-17", reference_close=41.18)
    by_id = {c["id"]: c for c in result["checks"]}
    assert result["pct"] < 60 and result["label"] in ("Baixa", "Média")
    assert by_id["mercado"]["status"] == "falhou"
    assert by_id["sentimento"]["status"] == "falhou"
    assert by_id["precos"]["status"] in ("falhou", "parcial") and "21.50" in by_id["precos"]["reason"]
    assert by_id["frescor"]["status"] == "parcial"  # balance sheet from 2025-12-31, 229 days old


def test_missing_reference_price_is_not_held_against_the_analysis():
    result = assess_confidence(_good_events(), "2026-07-06", reference_close=None)
    price = next(c for c in result["checks"] if c["id"] == "precos")
    assert price["status"] == "n/a" and price["score"] is None


def test_disagreeing_decision_stages_lower_the_agreement_check():
    events = _good_events()
    events[-2] = _ev("stage", "7. Trader (proposta de operação) → Buy · Comprar.")
    events[-1] = _ev("stage", "9. Portfolio Manager (decisão final) → Sell · Vender.")
    agreement = next(c for c in assess_confidence(events, "2026-07-06", 41.18)["checks"] if c["id"] == "acordo")
    assert agreement["status"] == "falhou"  # Buy against Sell: opposite directions

    # Hold against Sell is only one step apart, so it is a partial disagreement.
    events[-2] = _ev("stage", "7. Trader (proposta de operação) → Hold · Manter.")
    assert next(c for c in assess_confidence(events, "2026-07-06", 41.18)["checks"] if c["id"] == "acordo")["status"] == "parcial"


def test_structured_output_failures_and_tool_errors_are_counted():
    events = _good_events() + [
        _ev("warning", "tradingagents.agents.utils.structured: Trader: structured-output invocation failed; retrying once as free text"),
        _ev("tool_error", "get_news falhou após 1.0s"),
    ]
    by_id = {c["id"]: c for c in assess_confidence(events, "2026-07-06", 41.18)["checks"]}
    assert by_id["estrutura"]["status"] == "parcial" and "1 etapa" in by_id["estrutura"]["reason"]
    assert by_id["erros"]["status"] == "parcial"


def test_old_runs_without_recorded_stages_are_not_penalised_for_missing_text():
    events = [e for e in _good_events() if e["kind"] != "stage"]
    by_id = {c["id"]: c for c in assess_confidence(events, "2026-07-06", 41.18)["checks"]}
    assert by_id["mercado"]["status"] == "n/a" and "anterior ao registro" in by_id["mercado"]["reason"]
    assert by_id["dados"]["status"] == "ok"  # what WAS recorded is still audited
    result = assess_confidence(events, "2026-07-06", 41.18)
    assert result["coverage"] < 100  # and the score admits it rests on fewer criteria
    assert assess_confidence(_good_events(), "2026-07-06", 41.18)["coverage"] == 100


def test_no_events_at_all_gives_no_fabricated_percentage():
    result = assess_confidence([], "2026-07-06", None)
    # every check that cannot be evaluated is n/a or failed; nothing is invented as a pass
    assert all(c["status"] != "ok" or c["id"] in ("erros", "estrutura") for c in result["checks"])
