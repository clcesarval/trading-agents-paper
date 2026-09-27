from types import SimpleNamespace

from backend.app.analysis.confidence import assess_confidence
from backend.app.execution.market_forced import make_grounded_market_analyst

SNAPSHOT = "## Verified market data snapshot for PETR4.SA\n| rsi | 55.20 |\n| macd | -0.19 |\n| close_50_sma | 44.23 |"
STATE = {"company_of_interest": "PETR4.SA", "trade_date": "2026-08-17", "messages": []}


class _FakeLLM:
    def __init__(self, reply="Relatório: RSI 55.20 neutro; MACD -0.19 negativo; preço acima da SMA50 44.23."):
        self.reply, self.calls = reply, []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.reply)


def _factory(events, snapshot=lambda *a, **k: SNAPSHOT, fallback_marker="ORIGINAL"):
    original = lambda llm: (lambda state: {"messages": [], "market_report": fallback_marker})  # noqa: E731
    return make_grounded_market_analyst(
        original, lambda k, t: events.append((k, t)), snapshot,
        lambda state: "Instrument: PETR4.SA", lambda: "Write in Portuguese.",
    )


def test_indicators_are_computed_by_code_and_handed_to_the_model_which_only_writes():
    events, llm = [], _FakeLLM()
    node = _factory(events)(llm)
    out = node(STATE)

    assert out["market_report"].startswith("Relatório: RSI 55.20")
    assert out["messages"][0].tool_calls == []  # no tool loop: the graph moves straight on
    system, human = llm.calls[0]
    assert "ONLY" in system[1] or "MUST appear in the snapshot" in system[1]
    assert "rsi | 55.20" in human[1] and "2026-08-17" in human[1]  # the verified numbers reach the model
    assert any(k == "tool_response" and "get_verified_market_snapshot respondeu" in t for k, t in events)


def test_if_the_snapshot_cannot_be_built_the_original_analyst_runs_instead():
    def boom(*a, **k):
        raise ValueError("No OHLCV data available")

    events, llm = [], _FakeLLM()
    out = _factory(events, snapshot=boom)(llm)(STATE)
    assert out["market_report"] == "ORIGINAL" and llm.calls == []
    assert any(k == "tool_error" and "usando o analista original" in t for k, t in events)


def test_an_empty_model_answer_also_falls_back_instead_of_shipping_an_empty_report():
    events = []
    out = _factory(events)(_FakeLLM(reply="   "))(STATE)
    assert out["market_report"] == "ORIGINAL"


def test_confidence_recognises_the_snapshot_as_the_source_of_the_numbers():
    events = [{"kind": e[0], "text": e[1]} for e in []]
    events = [
        {"kind": "tool_response", "text": "get_verified_market_snapshot respondeu em 0.4s · ## Verified market data snapshot for PETR4.SA | rsi | 55.20 |"},
        {"kind": "stage", "text": "1. Analista de Mercado (relatório) · RSI 55.20, MACD -0.19, SMA50 44.23, ATR 1.31, Bollinger 47.35 (upper)."},
    ]
    by_id = {c["id"]: c for c in assess_confidence(events, "2026-08-17", 41.18)["checks"]}
    assert by_id["mercado"]["status"] == "ok"  # numbers came from code, not from memory
    assert "preços" not in by_id["dados"]["reason"] and "indicadores" not in by_id["dados"]["reason"]
