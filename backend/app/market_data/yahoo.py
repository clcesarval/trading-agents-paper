from typing import Any
import httpx


class YahooMarketDataProvider:
    def _ticker(self, symbol: str) -> str:
        symbol = symbol.upper().strip()
        return symbol if "." in symbol or "-" in symbol else f"{symbol}.SA"

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        ticker = self._ticker(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "AI-Trading-Platform/0.1"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
        meta = result.get("meta", {})
        closes = [v for v in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if v is not None]
        price = float(meta.get("regularMarketPrice") or closes[-1])
        previous = float(closes[-2]) if len(closes) > 1 else price
        return {"symbol": symbol.upper(), "ticker": ticker, "price": price, "previous_close": previous, "change": price - previous, "change_percent": ((price / previous) - 1) * 100 if previous else 0, "currency": meta.get("currency", "BRL"), "provider": "Yahoo Finance"}
