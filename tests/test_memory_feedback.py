import tradingagents.agents.utils.memory as memory_module
import tradingagents.graph.reflection as reflection_module
import tradingagents.llm_clients as llm_clients_module

from backend.app.analysis import memory_feedback


class _FakeClient:
    def get_llm(self):
        return "fake-llm"


class _FakeReflector:
    def __init__(self, llm):
        self.llm = llm

    def reflect_on_final_decision(self, final_decision, raw_return, alpha_return, benchmark_name="SPY"):
        return f"reflection for {final_decision[:10]} ({raw_return:+.1%}/{alpha_return:+.1%} vs {benchmark_name})"


class _FakeMemoryLog:
    calls = []

    def __init__(self, config):
        self.config = config

    def update_with_outcome(self, **kwargs):
        _FakeMemoryLog.calls.append(kwargs)


def _patch_everything(monkeypatch):
    monkeypatch.setattr(llm_clients_module, "create_llm_client", lambda **kwargs: _FakeClient())
    monkeypatch.setattr(reflection_module, "Reflector", _FakeReflector)
    monkeypatch.setattr(memory_module, "TradingMemoryLog", _FakeMemoryLog)
    _FakeMemoryLog.calls = []


def test_record_outcome_writes_a_reflection_when_the_return_is_known(monkeypatch):
    _patch_everything(monkeypatch)

    ok = memory_feedback.record_outcome(
        ticker="PETR4.SA", trade_date="2026-08-17", final_decision="**Rating**: Hold ...",
        raw_return=0.2247, alpha_return=0.1065, holding_days=20, resolution_date="2026-09-15",
        benchmark="^BVSP", model="qwen3:8b",
    )

    assert ok is True
    assert len(_FakeMemoryLog.calls) == 1
    call = _FakeMemoryLog.calls[0]
    assert call["ticker"] == "PETR4.SA" and call["trade_date"] == "2026-08-17"
    assert call["raw_return"] == 0.2247 and call["resolution_date"] == "2026-09-15"
    assert "22.5%" in call["reflection"] or "+22.5%" in call["reflection"]  # the reflection cites the real alpha/return


def test_record_outcome_is_a_noop_without_a_decision_or_a_return(monkeypatch):
    _patch_everything(monkeypatch)

    assert memory_feedback.record_outcome(
        ticker="PETR4.SA", trade_date="2026-08-17", final_decision=None,
        raw_return=0.22, alpha_return=0.10, holding_days=20, resolution_date="2026-09-15",
        benchmark="^BVSP", model="qwen3:8b",
    ) is False
    assert memory_feedback.record_outcome(
        ticker="PETR4.SA", trade_date="2026-08-17", final_decision="Hold",
        raw_return=None, alpha_return=None, holding_days=20, resolution_date=None,
        benchmark="^BVSP", model="qwen3:8b",
    ) is False
    assert _FakeMemoryLog.calls == []


def test_record_outcome_never_raises_when_the_llm_call_fails(monkeypatch):
    monkeypatch.setattr(llm_clients_module, "create_llm_client", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Ollama offline")))

    ok = memory_feedback.record_outcome(
        ticker="PETR4.SA", trade_date="2026-08-17", final_decision="**Rating**: Hold ...",
        raw_return=0.22, alpha_return=0.10, holding_days=20, resolution_date="2026-09-15",
        benchmark="^BVSP", model="qwen3:8b",
    )

    assert ok is False  # swallowed, not raised — a resolved backtest date must not be marked as failed over this
