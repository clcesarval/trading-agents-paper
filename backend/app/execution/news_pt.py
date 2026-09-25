"""Brazilian-Portuguese headlines from the Google News RSS search feed.

Replaces the Reddit/StockTwits inputs of the Sentiment Analyst: StockTwits is
blocked (403 even for AAPL) and Reddit rate-limits and, more importantly, only
serves recent posts, so both come back empty for any historical (backtest)
date. Google News accepts an ``after:``/``before:`` window, so it works for past
dates too. No API key.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

_URL = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
_UA = "Mozilla/5.0 (compatible; tradingagents-paper)"
_B3_RE = re.compile(r"^([A-Z]{4}[0-9]{1,2})(\.SA)?$")


def _query_term(ticker: str) -> str:
    match = _B3_RE.match(ticker.upper().strip())
    return match.group(1) if match else ticker.upper().strip()


def fetch_news_pt(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 12,
    timeout: float = 15.0,
) -> str:
    """Return recent pt-BR headlines as a plaintext block for prompt injection.

    A failed fetch is reported as ``<unavailable>``, never as "no news": the two
    are different claims. When ``end_date`` is given, items published after it
    are dropped (Google's ``before:`` is not exact), so a backtest never sees
    news from after the simulated date.
    """
    term = _query_term(ticker)
    query = term
    if start_date and end_date:
        before = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        query = f"{term} after:{start_date} before:{before}"
    url = _URL.format(q=urllib.parse.quote(query))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            root = ET.fromstring(resp.read(3 * 1024 * 1024))
    except Exception as exc:  # network, HTTP or parse failure
        return f"<Google News unavailable: {type(exc).__name__}; this is not an absence of news>"

    cutoff = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    floor = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    rows = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue  # cannot prove it is inside the window
        day = published.date()
        if (cutoff and day > cutoff) or (floor and day < floor):
            continue
        rows.append((published, title))
    rows.sort(key=lambda row: row[0], reverse=True)
    rows = rows[:limit]
    if not rows:
        window = f" between {start_date} and {end_date}" if start_date and end_date else ""
        return f"<no Google News headlines found for {term}{window}>"
    lines = [f"Google News (pt-BR) — {len(rows)} headlines about {term}:"]
    lines += [f"  [{published.strftime('%Y-%m-%d')}] {title}" for published, title in rows]
    return "\n".join(lines)
