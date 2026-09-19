from typing import Any
import httpx
from .errors import classify_httpx_error, EmptyResponse


class YahooMarketDataProvider:
    def _ticker(self, symbol: str) -> str:
        symbol = symbol.upper().strip()
        return symbol if "." in symbol or "-" in symbol else f"{symbol}.SA"

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        ticker = self._ticker(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
        try:
            async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "AI-Trading-Platform/0.1"}) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise classify_httpx_error(exc, "Yahoo Finance", ticker) from exc
        results = payload.get("chart", {}).get("result")
        if not results:
            raise EmptyResponse(f"Yahoo Finance: sem dados de gráfico para {ticker}")
        result = results[0]
        meta = result.get("meta", {})
        closes = [v for v in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if v is not None]
        price_raw = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        if price_raw is None:
            raise EmptyResponse(f"Yahoo Finance: preço ausente na resposta para {ticker}")
        price = float(price_raw)
        previous = float(closes[-2]) if len(closes) > 1 else price
        return {"symbol": symbol.upper(), "ticker": ticker, "price": price, "previous_close": previous, "change": price - previous, "change_percent": ((price / previous) - 1) * 100 if previous else 0, "currency": meta.get("currency", "BRL"), "provider": "Yahoo Finance"}
