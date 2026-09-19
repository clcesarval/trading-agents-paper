"""The Sentiment Analyst calls fetch_reddit_posts/fetch_stocktwits_messages as
plain functions (pre-fetched into its prompt), bypassing route_to_vendor — the
only other place that generates tool_request/tool_response log events. Without
this instrumentation those two calls are silent, so there is no way to tell
from the log whether Reddit/StockTwits actually returned data or came back
blocked (reported live: user could not tell if the sentiment source worked).
"""
from tradingagents.agents.analysts import sentiment_analyst

from backend.app.execution.worker import _install_monkeypatches


def test_reddit_and_stocktwits_calls_emit_request_and_response_events(monkeypatch):
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "r/stocks: 2 recent posts mentioning PETR4")
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "<stocktwits unavailable: HTTPError>")

    events: list[tuple[str, str]] = []
    _install_monkeypatches(lambda kind, text: events.append((kind, text)), "2026-01-01")

    reddit_result = sentiment_analyst.fetch_reddit_posts("PETR4")
    stocktwits_result = sentiment_analyst.fetch_stocktwits_messages("PETR4")

    # The wrapper must not swallow or alter the original return value.
    assert reddit_result == "r/stocks: 2 recent posts mentioning PETR4"
    assert stocktwits_result == "<stocktwits unavailable: HTTPError>"

    kinds = [kind for kind, _ in events]
    assert kinds.count("sentiment_request") == 2
    assert kinds.count("sentiment_response") == 2

    reddit_response = next(text for kind, text in events if kind == "sentiment_response" and "Reddit" in text)
    assert "2 recent posts mentioning PETR4" in reddit_response

    stocktwits_response = next(text for kind, text in events if kind == "sentiment_response" and "StockTwits" in text)
    assert "<stocktwits unavailable: HTTPError>" in stocktwits_response
