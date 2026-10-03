import pytest

from backend.app.agents import adapter as adapter_module
from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.config import settings
from backend.app.storage import db


class _StubOllama:
    async def list_models(self):
        return [{"name": "qwen3:8b"}]

    async def never_called(self):
        raise AssertionError("a non-ollama provider must never consult the Ollama model list")


@pytest.fixture(autouse=True)
def _reset_provider_settings(monkeypatch):
    # These tests flip llm_provider/llm_model/google_api_key; make sure every
    # test starts from the real default and nothing leaks between tests.
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "llm_model", "")
    monkeypatch.setattr(settings, "google_api_key", "")
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.mark.asyncio
async def test_default_provider_is_ollama_and_behaves_exactly_as_before(monkeypatch):
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")

    result = await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["provider"] == "ollama" and captured["model"] == "qwen3:8b"
    assert result["provider"] == "ollama"


@pytest.mark.asyncio
async def test_a_non_ollama_provider_skips_the_ollama_model_list_entirely(monkeypatch):
    # Real motivation: this must work even if Ollama's model list is empty,
    # stale, or Ollama itself is briefly unreachable — a cloud provider has
    # nothing to do with what's pulled locally.
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Buy", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    monkeypatch.setattr(settings, "llm_provider", "google")
    monkeypatch.setattr(settings, "llm_model", "gemini-2.5-flash-lite")
    monkeypatch.setattr(settings, "google_api_key", "test-key-123")

    class _OllamaThatMustNotBeAsked:
        async def list_models(self):
            raise AssertionError("google provider must not consult the Ollama model list")

    adapter = TradingAgentsAdapter(_OllamaThatMustNotBeAsked(), default_model="qwen3:8b")
    result = await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["provider"] == "google"
    assert captured["model"] == "gemini-2.5-flash-lite"
    assert captured["google_api_key"] == "test-key-123"
    assert result["provider"] == "google" and result["model"] == "gemini-2.5-flash-lite"


@pytest.mark.asyncio
async def test_nvidia_provider_forwards_its_own_key_under_its_own_field(monkeypatch):
    # Each provider's key travels under its own payload field
    # (f"{provider}_api_key") — worker.py looks it up generically by that
    # name, so a new provider only needs an entry in its env-var map, not a
    # new branch here.
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    monkeypatch.setattr(settings, "llm_provider", "nvidia")
    monkeypatch.setattr(settings, "llm_model", "deepseek-ai/deepseek-r1")
    monkeypatch.setattr(settings, "nvidia_api_key", "nvapi-test-456")

    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")
    result = await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["provider"] == "nvidia" and captured["nvidia_api_key"] == "nvapi-test-456"
    assert result["provider"] == "nvidia" and result["model"] == "deepseek-ai/deepseek-r1"


@pytest.mark.asyncio
async def test_openai_provider_forwards_its_own_key_under_its_own_field(monkeypatch):
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "gpt-6-luna")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-789")

    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")
    result = await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["provider"] == "openai" and captured["openai_api_key"] == "sk-test-789"
    assert result["provider"] == "openai" and result["model"] == "gpt-6-luna"


@pytest.mark.asyncio
async def test_the_historical_rating_note_reaches_the_payload_when_enough_history_exists(monkeypatch):
    for i in range(10):
        db.upsert_run({
            "id": f"hist-{i}", "kind": "backtest", "symbol": "PETR4.SA", "status": "COMPLETED",
            "started_at": "t0", "finished_at": "t1", "rating_5tier": "Hold", "alpha_return": 0.01,
        })
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")
    await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["historical_rating_note"] is not None
    assert "NOTA HISTÓRICA" in captured["historical_rating_note"]


@pytest.mark.asyncio
async def test_the_historical_rating_note_is_none_with_no_prior_history(monkeypatch):
    captured = {}

    async def fake_run_isolated(payload, events, timeout, on_start=None, cancel_check=None):
        captured.update(payload)
        return {"signal": "Hold", "is_review": False, "decision_text": "ok"}

    monkeypatch.setattr(adapter_module, "run_isolated", fake_run_isolated)
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")
    await adapter.analyze("PETR4", trade_date="2026-08-17")

    assert captured["historical_rating_note"] is None


@pytest.mark.asyncio
async def test_a_non_ollama_provider_without_a_configured_model_raises_clearly(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "google")
    # llm_model left empty by the fixture — no model configured for this provider.
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")

    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        await adapter.analyze("PETR4", trade_date="2026-08-17")
