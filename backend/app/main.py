from fastapi import FastAPI, HTTPException
from threading import Lock
from datetime import datetime, timezone
import httpx
import asyncio
import uuid
import logging
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .config import settings
from .llm.ollama import OllamaProvider
from .agents.adapter import TradingAgentsAdapter
from .market_data.yahoo import YahooMarketDataProvider
from .market_data.providers import BrapiProvider, AlphaVantageProvider, MarketDataProviderChain
from .news.providers import AlphaVantageNewsProvider, GdeltNewsProvider, NewsProviderChain

app = FastAPI(title="AI Trading Platform", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
ollama = OllamaProvider(settings.ollama_base_url)
agents = TradingAgentsAdapter(ollama, settings.ollama_model)
market_data = MarketDataProviderChain(YahooMarketDataProvider(), BrapiProvider(settings.brapi_api_key), AlphaVantageProvider(settings.alpha_vantage_api_key) if settings.alpha_vantage_api_key else None)
news_data = NewsProviderChain(AlphaVantageNewsProvider(settings.alpha_vantage_api_key), GdeltNewsProvider())
event_log: list[dict] = []
event_lock = Lock()
run_lock = asyncio.Lock()
run_state = {"id": None, "status": "IDLE", "symbol": None, "started_at": None}
execution_logger = logging.getLogger("uvicorn.error")


class HealthResponse(BaseModel):
    status: str
    trading_mode: str
    ollama: dict


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", trading_mode=settings.trading_mode.upper(), ollama=await ollama.health_check())


@app.get("/api/llm/providers")
async def providers() -> list[dict]:
    return [{"id": "ollama", "name": "Ollama", "local": True, "models": await ollama.list_models()}]

@app.get("/api/llm/status")
async def llm_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/ps")
            response.raise_for_status()
            models = response.json().get("models", [])
        return {"available": True, "running": models}
    except Exception as exc:
        return {"available": False, "running": [], "error": str(exc)}


@app.get("/api/overview")
async def overview() -> dict:
    return {"portfolio_value": 10000, "daily_pnl": 0, "total_return": 0, "cash": 10000, "positions": 0, "confidence": 0, "market_status": "PAPER READY"}

@app.post("/api/analyze")
async def analyze(payload: dict) -> dict:
    symbol = str(payload.get("symbol", "PETR4")).strip()
    if not symbol or len(symbol) > 20:
        return {"error": "Invalid symbol"}
    if run_lock.locked():
        raise HTTPException(status_code=409, detail={"status": "RUNNING", "message": "Já existe uma análise em execução. Aguarde a conclusão.", "run_id": run_state["id"]})
    await run_lock.acquire()
    run_id = uuid.uuid4().hex[:8]
    run_state.update({"id": run_id, "status": "RUNNING", "symbol": symbol.upper(), "started_at": datetime.now(timezone.utc).isoformat()})
    def add_event(event):
        recorded = {**event, "run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat()}
        with event_lock:
            event_log.append(recorded)
            del event_log[:-200]
        console_line = f"[execução {run_id}] [{event.get('kind', 'evento')}] {event.get('text', '')}"
        print(console_line, flush=True)
        execution_logger.debug(console_line)
    with event_lock: event_log.clear()
    add_event({"kind": "run", "text": f"Iniciando análise de {symbol.upper()}"})
    try:
        quote = await market_data.get_quote(symbol, add_event)
        add_event({"kind": "market_data", "text": f"Cotação confirmada por {quote.get('provider', 'fonte externa')}: {quote.get('ticker')} · {quote.get('price')} {quote.get('currency', '')}"})
    except Exception as exc:
        quote = {"error": f"Market data unavailable: {exc}"}
        add_event({"kind": "market_error", "text": quote["error"]})
    try:
        result = await agents.analyze(symbol, payload.get("model"), quote, add_event)
    except Exception as exc:
        add_event({"kind": "error", "text": str(exc)})
        run_state["status"] = "ERROR"
        run_lock.release()
        return {"symbol": symbol.upper(), "status": "ERROR", "error": str(exc), "source": "TradingAgentsGraph", "run_id": run_id, "logs": event_log}
    result["quote"] = quote
    result["status"] = "COMPLETED"
    result["run_id"] = run_id
    add_event({"kind": "complete", "text": f"Execução {run_id} concluída; resultado final entregue à interface."})
    run_state["status"] = "COMPLETED"
    run_lock.release()
    return result

@app.get("/api/analyze/logs")
async def logs() -> list[dict]:
        with event_lock: return list(event_log)

@app.get("/api/analyze/status")
async def analyze_status() -> dict:
    return dict(run_state)

@app.get("/api/debug")
async def debug() -> dict:
    with event_lock:
        return {"event_count": len(event_log), "events": list(event_log), "ollama_url": settings.ollama_base_url, "model": settings.ollama_model}

@app.get("/api/market/{symbol}")
async def market(symbol: str) -> dict:
    return await market_data.get_quote(symbol)

@app.get("/api/news/{symbol}")
async def news(symbol: str) -> dict:
    return await news_data.get_news(symbol)
