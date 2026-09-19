import pytest
from backend.app.config import Settings


def test_paper_only():
    Settings(trading_mode="PAPER").validate_paper_only()
    with pytest.raises(RuntimeError):
        Settings(trading_mode="LIVE").validate_paper_only()
