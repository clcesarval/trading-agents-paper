from typing import Any
import asyncio
import time
import httpx
from .errors import classify_httpx_error, EmptyResponse, MarketDataError
from .yahoo import YahooMarketDataProvider


class BrapiProvider:
    def __init__(self, token: str = ""): self.token = token
    async def get_quote(self, symbol: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}" } if self.token else {}
        ticker = symbol.replace(".SA", "")
        try:
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                response = await client.get("https://brapi.dev/api/v2/stocks/quote", params={"symbols": ticker})
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise classify_httpx_error(exc, "Brapi", ticker) from exc
        results = payload.get("results")
        if not results:
            raise EmptyResponse(f"Brapi: sem resultados para {ticker}")
        item = results[0]
        if item.get("regularMarketPrice") is None:
            raise EmptyResponse(f"Brapi: preço ausente para {ticker}")
        return {"symbol": symbol.upper(), "ticker": item.get("symbol", symbol.upper()), "price": item["regularMarketPrice"], "previous_close": item.get("regularMarketPreviousClose", item["regularMarketPrice"]), "change": item.get("regularMarketChange", 0), "change_percent": item.get("regularMarketChangePercent", 0), "currency": item.get("currency", "BRL"), "provider": "brapi"}


class AlphaVantageProvider:
    def __init__(self, api_key: str): self.api_key = api_key
    async def get_quote(self, symbol: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get("https://www.alphavantage.co/query", params={"function":"GLOBAL_QUOTE", "symbol":symbol, "apikey":self.api_key})
                response.raise_for_status()
                data = response.json().get("Global Quote", {})
        except httpx.HTTPError as exc:
            raise classify_httpx_error(exc, "Alpha Vantage", symbol) from exc
        if not data or "05. price" not in data:
            raise EmptyResponse(f"Alpha Vantage: sem cotação para {symbol} (possível limite de requisições)")
        return {"symbol": symbol.upper(), "ticker": symbol.upper(), "price": float(data["05. price"]), "previous_close": float(data.get("08. previous close", data["05. price"])), "change": float(data.get("09. change", 0)), "change_percent": float(str(data.get("10. change percent", "0%")).strip("%")), "currency": "USD", "provider":"alpha_vantage"}


class MarketDataProviderChain:
    def __init__(self, yahoo, brapi, alpha=None, retries: int = 2, backoff_seconds: float = 1.0):
        self.providers = [yahoo, brapi] + ([alpha] if alpha else [])
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    @staticmethod
    def _error_details(exc: Exception) -> str:
        parts = []
        current: BaseException | None = exc
        while current is not None and len(parts) < 4:
            description = str(current).strip() or repr(current)
            parts.append(f"{type(current).__name__}: {description}")
            current = current.__cause__ or current.__context__
        return " <- ".join(parts)

    async def get_quote(self, symbol: str, on_event=None) -> dict[str, Any]:
        errors = []
        for provider in self.providers:
            provider_name = type(provider).__name__
            for attempt in range(1, self.retries + 1):
                started = time.perf_counter()
                if on_event:
                    on_event({"kind": "external_request", "text": f"{provider_name}: consultando {symbol.upper()} (tentativa {attempt}/{self.retries})"})
                try:
                    result = await provider.get_quote(symbol)
                    elapsed = time.perf_counter() - started
                    if on_event:
                        on_event({"kind": "external_response", "text": f"{provider_name}: resposta recebida em {elapsed:.2f}s · preço {result.get('price')} {result.get('currency', '')}"})
                    result["provider"] = result.get("provider", provider_name)
                    return result
                except (MarketDataError, Exception) as exc:
                    elapsed = time.perf_counter() - started
                    detail = self._error_details(exc)
                    if on_event:
                        on_event({"kind": "external_error", "text": f"{provider_name}: tentativa {attempt}/{self.retries} rejeitada após {elapsed:.2f}s · {detail}"})
                    if attempt == self.retries:
                        errors.append(f"{provider_name}: {detail}")
                    else:
                        await asyncio.sleep(self.backoff_seconds * attempt)
        raise RuntimeError("Nenhuma fonte de mercado respondeu: " + " | ".join(errors))
