import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module.settings, "database_url", f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(main_module.app) as test_client:
        yield test_client


def _mock_quote_ok(monkeypatch):
    async def fake_get_quote(symbol, on_event=None):
        return {"symbol": symbol.upper(), "ticker": f"{symbol.upper()}.SA", "price": 10.0, "currency": "BRL", "provider": "fake"}
    monkeypatch.setattr(main_module.market_data, "get_quote", fake_get_quote)


def test_second_analyze_returns_409_while_first_is_running(client, monkeypatch):
    _mock_quote_ok(monkeypatch)

    async def slow_analyze(symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None):
        if on_pid:
            on_pid(999999)
        await asyncio.sleep(0.6)
        return {"decision": "HOLD", "rating_5tier": "Hold", "is_review": False, "confidence": None, "summary": "ok", "model": "qwen2.5:3b", "provider": "ollama", "agents": []}

    monkeypatch.setattr(main_module.agents, "analyze", slow_analyze)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/api/analyze", json={"symbol": "PETR4"})
        time.sleep(0.15)
        second = pool.submit(client.post, "/api/analyze", json={"symbol": "PETR4"})
        first_response = first.result()
        second_response = second.result()

    assert first_response.status_code == 200
    assert first_response.json()["status"] == "COMPLETED"
    assert second_response.status_code == 409
    detail = second_response.json()["detail"]
    assert detail["status"] == "RUNNING"
    assert "run_id" in detail


def test_status_never_reports_completed_without_a_real_decision(client, monkeypatch):
    _mock_quote_ok(monkeypatch)

    async def review_analyze(symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None):
        return {"decision": None, "rating_5tier": "REVIEW", "is_review": True, "confidence": None, "summary": "sem rating reconhecível", "model": "qwen2.5:3b", "provider": "ollama", "agents": []}

    monkeypatch.setattr(main_module.agents, "analyze", review_analyze)

    response = client.post("/api/analyze", json={"symbol": "PETR4"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INCONCLUSIVE"
    assert body["decision"] is None

    status = client.get("/api/analyze/status").json()
    assert status["status"] == "INCONCLUSIVE"
    assert status["result"]["decision"] is None


def test_status_and_run_id_are_consistent_after_completion(client, monkeypatch):
    _mock_quote_ok(monkeypatch)

    async def ok_analyze(symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None):
        return {"decision": "BUY", "rating_5tier": "Buy", "is_review": False, "confidence": None, "summary": "tendência positiva", "model": "qwen2.5:3b", "provider": "ollama", "agents": []}

    monkeypatch.setattr(main_module.agents, "analyze", ok_analyze)

    posted = client.post("/api/analyze", json={"symbol": "vale3"}).json()
    assert posted["status"] == "COMPLETED"
    run_id = posted["run_id"]

    status = client.get("/api/analyze/status").json()
    assert status["id"] == run_id
    assert status["status"] == "COMPLETED"
    assert status["result"]["run_id"] == run_id
    assert status["result"]["decision"] == "BUY"

    logs = client.get("/api/analyze/logs").json()
    assert any(entry["kind"] == "complete" for entry in logs)


def test_analyze_error_path_never_marks_completed(client, monkeypatch):
    _mock_quote_ok(monkeypatch)

    async def failing_analyze(symbol, model=None, quote=None, events=None, trade_date=None, on_pid=None):
        raise RuntimeError("Ollama indisponível")

    monkeypatch.setattr(main_module.agents, "analyze", failing_analyze)

    response = client.post("/api/analyze", json={"symbol": "PETR4"})
    body = response.json()
    assert body["status"] == "ERROR"
    assert "Ollama indisponível" in body["error"]

    status = client.get("/api/analyze/status").json()
    assert status["status"] == "ERROR"
