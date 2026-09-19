from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.execution.worker import clamp_future_date, is_b3_ticker, resolve_date_alias, to_b3_ticker


def test_b3_ticker_detection_and_suffix():
    assert is_b3_ticker("PETR4") is True
    assert is_b3_ticker("petr4") is True
    assert to_b3_ticker("petr4") == "PETR4.SA"
    assert is_b3_ticker("AAPL") is False
    assert is_b3_ticker("PETR4.SA") is False


def test_adapter_normalize_symbol_appends_sa_suffix():
    assert TradingAgentsAdapter.normalize_symbol("PETR4") == "PETR4.SA"
    assert TradingAgentsAdapter.normalize_symbol("petr4") == "PETR4.SA"


def test_adapter_normalize_symbol_keeps_existing_suffix():
    assert TradingAgentsAdapter.normalize_symbol("PETR4.SA") == "PETR4.SA"


def test_resolve_date_alias_replaces_natural_language():
    today = "2026-09-18"
    for alias in ("now", "today", "current", "hoje", "HOJE", "  Now  "):
        assert resolve_date_alias(alias, today) == today


def test_resolve_date_alias_keeps_explicit_dates():
    assert resolve_date_alias("2026-01-05", "2026-09-18") == "2026-01-05"


def test_clamp_future_date_caps_a_hallucinated_end_date():
    # A small local model can invent an end_date past the run's own trade
    # date; that must not be sent to yfinance as-is (it would find no rows
    # that recent and the upstream staleness guard would kill the analysis).
    assert clamp_future_date("2026-12-31", "2026-09-19") == "2026-09-19"


def test_clamp_future_date_keeps_dates_on_or_before_as_of():
    assert clamp_future_date("2026-09-19", "2026-09-19") == "2026-09-19"
    assert clamp_future_date("2026-01-05", "2026-09-19") == "2026-01-05"
