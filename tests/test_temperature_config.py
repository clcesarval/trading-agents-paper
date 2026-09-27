import pytest

from backend.app.agents import adapter as adapter_module
from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.config import settings


class _StubOllama:
    async def list_models(self):
        return [{"name": "qwen3:8b"}]


@pytest.mark.asyncio
async def test_analyze_forwards_the_configured_temperature_to_the_worker_payload(monkeypatch):
    # Real motivation: Ollama's default sampling temperature was a silent,
    # unset knob — nothing forwarded it, so every agent (including the
    # decision stages) sampled at whatever Ollama defaults to. This is the
    # one place every call (live analysis and backtest) builds that payload.
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")

    await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["temperature"] == settings.llm_temperature


@pytest.mark.asyncio
async def test_an_empty_temperature_setting_is_forwarded_as_is(monkeypatch):
    # "" must reach the worker unchanged (it means "leave the model default"),
    # never silently coerced to 0.0 — those are very different sampling settings.
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    monkeypatch.setattr(settings, "llm_temperature", "")
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")

    await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["temperature"] == ""


def test_default_temperature_is_low_but_not_zero():
    # 0.2: low enough to cut down sampling noise (the measured source of
    # same-date-different-decision instability) without fully flattening the
    # distribution, since Qwen3's "thinking" tokens are sampled too either way.
    assert settings.llm_temperature == 0.2
