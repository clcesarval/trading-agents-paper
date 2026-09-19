from typing import Any
import asyncio
import httpx


class AlphaVantageNewsProvider:
    def __init__(self, api_key: str): self.api_key = api_key
    async def get_news(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.api_key: raise RuntimeError("ALPHA_VANTAGE_API_KEY não configurada")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://www.alphavantage.co/query", params={"function":"NEWS_SENTIMENT", "tickers":symbol.replace(".SA", ""), "limit":limit, "apikey":self.api_key})
            response.raise_for_status(); feed = response.json().get("feed", [])
        return [{"title": x.get("title", ""), "summary": x.get("summary", ""), "url": x.get("url", ""), "sentiment": x.get("overall_sentiment_label", "neutral"), "source": "alpha_vantage"} for x in feed[:limit]]


class GdeltNewsProvider:
    async def get_news(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        query = symbol.replace(".SA", "")
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query":f'"{query}"', "mode":"artlist", "format":"json", "maxrecords":limit, "sort":"datedesc"})
            response.raise_for_status(); articles = response.json().get("articles", [])
        return [{"title": x.get("title", ""), "summary": "", "url": x.get("url", ""), "sentiment": "unclassified", "source": "gdelt"} for x in articles[:limit]]


class NewsProviderChain:
    def __init__(self, *providers, retries: int = 2, backoff_seconds: float = 1.0):
        self.providers = [p for p in providers if p]
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    async def get_news(self, symbol: str, limit: int = 5) -> dict[str, Any]:
        errors = []
        for provider in self.providers:
            provider_name = provider.__class__.__name__
            for attempt in range(1, self.retries + 1):
                try:
                    items = await provider.get_news(symbol, limit)
                    if items:
                        return {"provider": provider_name, "items": items}
                    break  # empty result is not transient; try the next provider
                except Exception as exc:
                    detail = f"{type(exc).__name__}: {exc}"
                    if attempt == self.retries:
                        errors.append(f"{provider_name}: {detail}")
                    else:
                        await asyncio.sleep(self.backoff_seconds * attempt)
        return {"provider": "none", "items": [], "errors": errors}
