import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from threading import Lock
from datetime import datetime, timezone
import httpx
import asyncio
import json
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
from . import power
from .analysis.confidence import assess_confidence
from .storage import db
from .backtest.service import BacktestService

event_log: list[dict] = []
event_lock = Lock()
run_lock = asyncio.Lock()
run_state = {"id": None, "status": "IDLE", "symbol": None, "started_at": None}
execution_logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(settings.database_url)
    orphan_runs = db.reconcile_orphan_runs("Execução interrompida por reinício do servidor (Uvicorn reload/crash).")
    orphan_jobs = db.reconcile_orphan_backtest_jobs("Job de backtest interrompido por reinício do servidor.")
    if orphan_runs:
        print(f"[startup] {len(orphan_runs)} execução(oes) órfã(s) marcada(s) como ERROR: {orphan_runs}", flush=True)
    if orphan_jobs:
        print(f"[startup] {len(orphan_jobs)} job(s) de backtest órfão(s) marcado(s) como ERROR: {orphan_jobs}", flush=True)
    last = db.get_last_run("live")
    if last and last["status"] != "RUNNING":
        run_state.update({"id": last["id"], "status": last["status"], "symbol": last["symbol"], "started_at": last["started_at"]})
    yield


app = FastAPI(title="AI Trading Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
ollama = OllamaProvider(settings.ollama_base_url)
agents = TradingAgentsAdapter(ollama, settings.ollama_model)
market_data = MarketDataProviderChain(YahooMarketDataProvider(), BrapiProvider(settings.brapi_api_key), AlphaVantageProvider(settings.alpha_vantage_api_key) if settings.alpha_vantage_api_key else None)
news_data = NewsProviderChain(AlphaVantageNewsProvider(settings.alpha_vantage_api_key), GdeltNewsProvider())
backtest_service = BacktestService(agents, run_lock)


class HealthResponse(BaseModel):
    status: str
    trading_mode: str
    ollama: dict


def _elapsed_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    """Wall-clock duration between two ISO timestamps, or None if either is missing
    or unparseable — never a fabricated 0."""
    if not started_at or not finished_at:
        return None
    try:
        return round((datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


def _run_row_to_result(row: dict) -> dict:
    return {
        "symbol": row.get("symbol"),
        "status": row.get("status"),
        "decision": row.get("decision"),
        "rating_5tier": row.get("rating_5tier"),
        "is_review": row.get("status") == "INCONCLUSIVE",
        "confidence": None,
        "summary": row.get("summary"),
        "error": row.get("error"),
        "model": row.get("model"),
        "provider": row.get("provider"),
        "quote": row.get("quote"),
        "run_id": row.get("id"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "duration_seconds": _elapsed_seconds(row.get("started_at"), row.get("finished_at")),
        "confidence": row.get("confidence_pct"),
        "confidence_detail": row.get("confidence_detail"),
        "source": "TradingAgentsGraph",
    }


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
        if run_state.get("status") == "RUNNING":
            message = f"Já existe uma análise de {run_state.get('symbol')} em andamento desde {run_state.get('started_at')} (execução {run_state.get('id')}). Aguarde a conclusão."
        else:
            message = "O motor de IA local está ocupado (provavelmente rodando um backtest). Tente novamente em instantes."
        raise HTTPException(status_code=409, detail={"status": "RUNNING", "message": message, "run_id": run_state.get("id")})
    await run_lock.acquire()
    power.acquire()  # released in the finally below; keeps Windows from sleeping mid-analysis
    run_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    run_state.update({"id": run_id, "status": "RUNNING", "symbol": symbol.upper(), "started_at": started_at})
    with event_lock:
        event_log.clear()
    db.upsert_run({"id": run_id, "kind": "live", "backtest_job_id": None, "symbol": symbol.upper(), "trade_date": None, "status": "RUNNING", "started_at": started_at, "logs": []})

    def add_event(event):
        recorded = {**event, "run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat()}
        with event_lock:
            event_log.append(recorded)
            del event_log[:-2000]
            snapshot = list(event_log)
        console_line = f"[execução {run_id}] [{event.get('kind', 'evento')}] {event.get('text', '')}"
        print(console_line, flush=True)
        execution_logger.debug(console_line)
        db.upsert_run({"id": run_id, "logs": snapshot})

    def on_pid(pid: int) -> None:
        db.upsert_run({"id": run_id, "pid": pid})

    try:
        add_event({"kind": "run", "text": f"Iniciando análise de {symbol.upper()}"})
        market_confirmed = True
        try:
            quote = await market_data.get_quote(symbol, add_event)
            add_event({"kind": "market_data", "text": f"Cotação confirmada por {quote.get('provider', 'fonte externa')}: {quote.get('ticker')} · {quote.get('price')} {quote.get('currency', '')}"})
        except Exception as exc:
            quote = {"error": f"Market data unavailable: {exc}"}
            market_confirmed = False
            add_event({"kind": "market_error", "text": f"{quote['error']} · TradingAgents ainda tentará obter dados por conta própria."})

        try:
            result = await agents.analyze(symbol, payload.get("model"), quote, add_event, on_pid=on_pid)
        except Exception as exc:
            finished_at = datetime.now(timezone.utc).isoformat()
            add_event({"kind": "error", "text": str(exc)})
            run_state["status"] = "ERROR"
            db.upsert_run({"id": run_id, "status": "ERROR", "error": str(exc), "finished_at": finished_at, "quote": quote, "logs": list(event_log)})
            return {"symbol": symbol.upper(), "status": "ERROR", "error": str(exc), "source": "TradingAgentsGraph", "run_id": run_id, "logs": event_log, "duration_seconds": _elapsed_seconds(started_at, finished_at)}

        status = "INCONCLUSIVE" if result.get("is_review") else "COMPLETED"
        finished_at = datetime.now(timezone.utc).isoformat()
        result["quote"] = quote
        result["market_data_confirmed"] = market_confirmed
        result["run_id"] = run_id
        result["status"] = status
        result["duration_seconds"] = _elapsed_seconds(started_at, finished_at)
        add_event({"kind": "complete", "text": f"Execução {run_id} finalizada como {status} em {result['duration_seconds']}s."})
        run_state["status"] = status
        # Objective 0-100 score of how well-grounded the reading was (never a number
        # the model made up). The live reference price is the confirmed quote.
        confidence = assess_confidence(list(event_log), started_at[:10], quote.get("price") if isinstance(quote, dict) else None)
        result["confidence"] = confidence["pct"]
        result["confidence_detail"] = confidence
        db.upsert_run({
            "id": run_id, "status": status, "decision": result.get("decision"), "rating_5tier": result.get("rating_5tier"),
            "summary": result.get("summary"), "model": result.get("model"), "provider": result.get("provider"),
            "finished_at": finished_at, "quote": quote, "logs": list(event_log),
            "confidence_pct": confidence["pct"], "confidence_json": json.dumps(confidence, ensure_ascii=False),
        })
        return result
    except Exception as exc:
        # Belt-and-braces: any unexpected failure (including a storage bug)
        # must still surface as ERROR and release the lock below, never leave
        # run_state stuck on RUNNING forever or leak the lock to future runs.
        finished_at = datetime.now(timezone.utc).isoformat()
        run_state["status"] = "ERROR"
        try:
            db.upsert_run({"id": run_id, "status": "ERROR", "error": str(exc), "finished_at": finished_at})
        except Exception:
            pass
        return {"symbol": symbol.upper(), "status": "ERROR", "error": f"Falha inesperada: {exc}", "source": "TradingAgentsGraph", "run_id": run_id, "logs": list(event_log), "duration_seconds": _elapsed_seconds(started_at, finished_at)}
    finally:
        power.release()
        run_lock.release()

@app.get("/api/analyze/logs")
async def logs() -> list[dict]:
    with event_lock:
        current = list(event_log)
    if current:
        return current
    if run_state.get("id"):
        row = db.get_run(run_state["id"])
        if row:
            return row.get("logs", [])
    return []

@app.get("/api/analyze/status")
async def analyze_status() -> dict:
    state = dict(run_state)
    if state.get("id"):
        row = db.get_run(state["id"])
        if row:
            state["result"] = _run_row_to_result(row)
    return state

@app.get("/api/debug")
async def debug() -> dict:
    with event_lock:
        return {"event_count": len(event_log), "events": list(event_log), "ollama_url": settings.ollama_base_url, "model": settings.ollama_model, "analysis_timeout_seconds": settings.analysis_timeout_seconds}

@app.get("/api/market/{symbol}")
async def market(symbol: str) -> dict:
    return await market_data.get_quote(symbol)

@app.get("/api/news/{symbol}")
async def news(symbol: str) -> dict:
    return await news_data.get_news(symbol)


@app.post("/api/backtest")
async def start_backtest(payload: dict) -> dict:
    symbol = str(payload.get("symbol", "")).strip()
    start_date = str(payload.get("start_date", "")).strip()
    end_date = str(payload.get("end_date", "")).strip()
    holding_days = int(payload.get("holding_days", 5))
    if not symbol or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="symbol, start_date e end_date são obrigatórios (YYYY-MM-DD)")
    try:
        job = backtest_service.create_job(symbol, start_date, end_date, holding_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(backtest_service.run_job(job["id"]))
    return job

@app.get("/api/backtest")
async def list_backtests() -> list[dict]:
    return db.list_backtest_jobs()

@app.get("/api/backtest/{job_id}")
async def get_backtest(job_id: str) -> dict:
    job = db.get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    job["runs"] = db.list_runs(kind="backtest", backtest_job_id=job_id)
    return job

@app.post("/api/backtest/{job_id}/retry")
async def retry_backtest(job_id: str) -> dict:
    job = db.get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backtest não encontrado")
    if job["status"] in ("QUEUED", "RUNNING"):
        raise HTTPException(status_code=409, detail="Este backtest já está em andamento")
    db.update_backtest_job(job_id, status="QUEUED", cancel_requested=0, error=None)
    asyncio.create_task(backtest_service.run_job(job_id))
    return db.get_backtest_job(job_id)


@app.post("/api/backtest/{job_id}/redo/{trade_date}")
async def redo_backtest_date(job_id: str, trade_date: str) -> dict:
    job = db.get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backtest não encontrado")
    if job["status"] in ("QUEUED", "RUNNING"):
        raise HTTPException(status_code=409, detail="Este backtest já está em andamento")
    if not db.get_run(f"{job_id}-{trade_date}"):
        raise HTTPException(status_code=404, detail="Essa data não pertence a este backtest")
    backtest_service.reset_date(job_id, trade_date)
    db.update_backtest_job(job_id, status="QUEUED", cancel_requested=0, error=None)
    asyncio.create_task(backtest_service.run_job(job_id))
    return db.get_backtest_job(job_id)


@app.post("/api/backtest/{job_id}/recompute-confidence")
async def recompute_backtest_confidence(job_id: str) -> dict:
    if not db.get_backtest_job(job_id):
        raise HTTPException(status_code=404, detail="Backtest não encontrado")
    return {"scored_runs": await backtest_service.recompute_confidence(job_id)}


@app.post("/api/backtest/{job_id}/cancel")
async def cancel_backtest(job_id: str) -> dict:
    if not db.get_backtest_job(job_id):
        raise HTTPException(status_code=404, detail="Job não encontrado")
    backtest_service.request_cancel(job_id)
    return {"cancel_requested": True}
