import pytest
from backend.app.agents import adapter as adapter_module
from backend.app.agents.adapter import TradingAgentsAdapter


class FakeOllama:
    async def list_models(self):
        return [{"name": "qwen2.5:3b"}]


def _patch_run_isolated(monkeypatch, final: dict):
    async def fake_run_isolated(payload, on_event, timeout, on_start=None):
        if on_start:
            on_start(12345)
        return final
    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)


@pytest.mark.asyncio
async def test_review_signal_never_becomes_buy(monkeypatch):
    _patch_run_isolated(monkeypatch, {"signal": "REVIEW", "is_review": True, "decision_text": "resposta sem rating reconhecível"})
    result = await TradingAgentsAdapter(FakeOllama()).analyze("PETR4")
    assert result["is_review"] is True
    assert result["decision"] is None
    assert result["rating_5tier"] == "REVIEW"
    assert result["confidence"] is None


@pytest.mark.parametrize("signal,expected", [
    ("Buy", "BUY"), ("Overweight", "BUY"),
    ("Hold", "HOLD"),
    ("Underweight", "SELL"), ("Sell", "SELL"),
])
@pytest.mark.asyncio
async def test_five_tier_rating_maps_to_simple_badge(monkeypatch, signal, expected):
    _patch_run_isolated(monkeypatch, {"signal": signal, "is_review": False, "decision_text": f"Rating: {signal}"})
    result = await TradingAgentsAdapter(FakeOllama()).analyze("PETR4")
    assert result["decision"] == expected
    assert result["rating_5tier"] == signal
    assert result["is_review"] is False
    assert result["confidence"] is None


@pytest.mark.asyncio
async def test_no_model_available_raises_instead_of_faking_a_decision():
    class EmptyOllama:
        async def list_models(self):
            return []

    with pytest.raises(RuntimeError, match="Nenhum modelo Ollama disponível"):
        await TradingAgentsAdapter(EmptyOllama(), default_model="does-not-exist").analyze("PETR4")
