from backend.app.execution.worker import stage_summaries

FULL_STATE = {
    "market_report": "Tendência de baixa, MACD negativo.",
    "sentiment_report": "Sentimento neutro.",
    "news_report": "Petróleo em queda.",
    "fundamentals_report": "Dívida alta.",
    "investment_debate_state": {"history": "Bull: comprar. Bear: vender."},
    "investment_plan": "**Recommendation**: Sell\n\nA tendência é de baixa e os riscos dominam.",
    "trader_investment_plan": "Proposta cautelosa.\nFINAL TRANSACTION PROPOSAL: **HOLD**",
    "risk_debate_state": {"history": "Agressivo: ... Conservador: ... Neutro: ..."},
    "final_trade_decision": "**Rating**: Hold",
}


def test_every_pipeline_stage_is_listed_in_reasoning_order():
    lines = stage_summaries(FULL_STATE)
    assert [line.split(".")[0] for line in lines] == ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
    assert "Tendência de baixa" in lines[0]
    assert "Bull: comprar" in lines[4]  # nested debate history is read
    assert "Conservador" in lines[7]


def test_only_decision_stages_show_a_detected_rating():
    lines = stage_summaries(FULL_STATE)
    assert "→ Sell" in lines[5]  # Research Manager
    assert "→ Hold" in lines[6]  # Trader
    assert "→ Hold" in lines[8]  # Portfolio Manager
    assert "→" not in lines[0] and "→" not in lines[4]  # analyst reports / debates are not ratings


def test_missing_or_unrated_stage_is_reported_honestly_not_defaulted():
    lines = stage_summaries({"investment_plan": "texto sem nenhuma recomendação clara"})
    assert "nenhum rating reconhecido" in lines[5]
    assert "sem texto" in lines[6]
    assert "sem texto" in lines[0]


def test_long_text_is_truncated_for_the_log():
    lines = stage_summaries({"investment_plan": "Hold " + "x " * 2000}, limit=100)
    assert lines[5].endswith("…") and len(lines[5]) < 300
