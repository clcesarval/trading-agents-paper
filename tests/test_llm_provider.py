import pytest

from backend.app.agents import adapter as adapter_module
from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.config import settings


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
async def test_a_non_ollama_provider_without_a_configured_model_raises_clearly(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "google")
    # llm_model left empty by the fixture — no model configured for this provider.
    adapter = TradingAgentsAdapter(_StubOllama(), default_model="qwen3:8b")

    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        await adapter.analyze("PETR4", trade_date="2026-08-17")
