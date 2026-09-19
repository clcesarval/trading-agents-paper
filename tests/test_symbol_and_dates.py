from backend.app.agents.adapter import TradingAgentsAdapter
from backend.app.execution.worker import is_b3_ticker, to_b3_ticker, resolve_date_alias


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
