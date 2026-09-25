"""The Sentiment Analyst pre-fetches its sources as plain function calls, bypassing
route_to_vendor (the only place that logs tool_request/tool_response), so without
this instrumentation they are invisible in the run log. Reddit/StockTwits were
replaced by pt-BR Google News (Reddit slot) and a network-free "disabled"
placeholder (StockTwits slot); both must still be logged.
"""
from tradingagents.agents.analysts import sentiment_analyst

from backend.app.execution import news_pt
from backend.app.execution.worker import _install_monkeypatches


def test_news_and_stocktwits_slots_emit_request_and_response_events(monkeypatch):
    monkeypatch.setattr(news_pt, "fetch_news_pt", lambda *a, **k: "Google News (pt-BR) — 2 headlines about PETR4:")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "original reddit, must not be used")
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "original stocktwits, must not be used")

    events: list[tuple[str, str]] = []
    _install_monkeypatches(lambda kind, text: events.append((kind, text)), "2026-01-01")

    news_result = sentiment_analyst.fetch_reddit_posts("PETR4", start_date="2025-12-25", end_date="2026-01-01")
    stocktwits_result = sentiment_analyst.fetch_stocktwits_messages("PETR4", limit=30)

    assert news_result == "Google News (pt-BR) — 2 headlines about PETR4:"
    assert "StockTwits desativado" in stocktwits_result

    kinds = [kind for kind, _ in events]
    assert kinds.count("sentiment_request") == 2
    assert kinds.count("sentiment_response") == 2
    assert any("Google News" in text and "2 headlines" in text for kind, text in events if kind == "sentiment_response")
    assert any("StockTwits desativado" in text for kind, text in events if kind == "sentiment_response")
