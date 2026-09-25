import io

from backend.app.execution import news_pt

_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Petrobras (PETR4) sobe com petróleo</title><pubDate>Mon, 06 Jul 2026 07:00:00 GMT</pubDate></item>
<item><title>Noticia do dia seguinte (nao pode aparecer)</title><pubDate>Tue, 07 Jul 2026 07:00:00 GMT</pubDate></item>
<item><title>Antiga demais</title><pubDate>Mon, 01 Jun 2026 07:00:00 GMT</pubDate></item>
<item><title>Sem data valida</title><pubDate>lixo</pubDate></item>
<item><title>Produção recorde &amp; dividendos</title><pubDate>Fri, 03 Jul 2026 07:00:00 GMT</pubDate></item>
</channel></rss>"""


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_headlines_are_windowed_so_a_backtest_never_sees_the_future(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return _Resp(_RSS.encode("utf-8"))

    monkeypatch.setattr(news_pt.urllib.request, "urlopen", fake_urlopen)
    out = news_pt.fetch_news_pt("PETR4.SA", start_date="2026-06-29", end_date="2026-07-06")

    assert "PETR4" in seen["url"] and "PETR4.SA" not in seen["url"]  # bare B3 code in the query
    assert "after%3A2026-06-29" in seen["url"]
    assert "Petrobras (PETR4) sobe com petróleo" in out
    assert "Produção recorde & dividendos" in out  # html entities decoded
    assert "dia seguinte" not in out  # published after the analysis date
    assert "Antiga demais" not in out  # before the window
    assert "Sem data valida" not in out  # cannot prove it is in the window
    assert out.index("2026-07-06") < out.index("2026-07-03")  # newest first


def test_failed_fetch_is_reported_as_unavailable_not_as_no_news(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("sem rede")

    monkeypatch.setattr(news_pt.urllib.request, "urlopen", boom)
    out = news_pt.fetch_news_pt("PETR4", start_date="2026-06-29", end_date="2026-07-06")
    assert out.startswith("<Google News unavailable")
    assert "not an absence of news" in out


def test_empty_window_says_no_headlines(monkeypatch):
    monkeypatch.setattr(news_pt.urllib.request, "urlopen", lambda req, timeout=0: _Resp(b"<rss><channel></channel></rss>"))
    out = news_pt.fetch_news_pt("PETR4", start_date="2026-06-29", end_date="2026-07-06")
    assert out.startswith("<no Google News headlines found")
