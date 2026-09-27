"""The raw material a run actually saw, kept in memory for the end-of-run number audit.

Each analysis runs in its own process, so a module-level list is per-run. Tool outputs
are recorded in full here (the run log only keeps a 900-character excerpt of each), which
is what lets the audit tell "no tool ever returned this number" from "the excerpt was cut".
"""
from __future__ import annotations

_sources: list[str] = []
_snapshot: list[str] = []

_MAX_PRICE_LINES = 80  # get_stock_data can return the whole price history; only recent rows matter


def reset() -> None:
    _sources.clear()
    _snapshot.clear()


def record(method: str, output: object) -> None:
    text = str(output)
    if method == "get_stock_data":
        text = "\n".join(text.splitlines()[-_MAX_PRICE_LINES:])
    _sources.append(text)


def record_snapshot(text: str) -> None:
    _snapshot.append(text)
    _sources.append(text)


def sources() -> list[str]:
    return list(_sources)


def snapshot() -> str | None:
    return "\n".join(_snapshot) if _snapshot else None
