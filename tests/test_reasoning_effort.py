from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI

from backend.app.execution.worker import _install_reasoning_effort


def _stub_request_payload(monkeypatch):
    # Registering the stub through monkeypatch also restores the real method after the test.
    monkeypatch.setattr(NormalizedChatOpenAI, "_get_request_payload", lambda self, input_, *, stop=None, **kw: {"model": "qwen3:14b", "messages": []})


def test_reasoning_effort_is_injected_into_every_request_payload(monkeypatch):
    _stub_request_payload(monkeypatch)
    events = []
    _install_reasoning_effort(lambda kind, text: events.append((kind, text)), "none")

    payload = NormalizedChatOpenAI._get_request_payload(object(), [])
    assert payload["reasoning_effort"] == "none"
    assert payload["model"] == "qwen3:14b"  # nothing else is touched
    assert any(kind == "config" and "reasoning_effort=none" in text for kind, text in events)


def test_empty_setting_leaves_requests_untouched(monkeypatch):
    _stub_request_payload(monkeypatch)
    before = NormalizedChatOpenAI._get_request_payload
    _install_reasoning_effort(lambda *a: None, "")
    assert NormalizedChatOpenAI._get_request_payload is before
    assert "reasoning_effort" not in NormalizedChatOpenAI._get_request_payload(object(), [])
