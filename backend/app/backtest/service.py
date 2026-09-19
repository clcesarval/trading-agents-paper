"""Sequential historical backtest: re-runs the real multi-agent pipeline for
each business day in the range, then scores it with the realized/alpha
return once price data is available.

This is NOT a fast vectorized backtest — each date costs the same wall-clock
time as a live analysis, because it re-invokes the full LangGraph pipeline
(same ``TradingAgentsAdapter.analyze`` used by /api/analyze, same shared
``run_lock`` so it never competes with a live analysis for the local
Ollama/GPU slot).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG

from ..storage import db


def _business_dates(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end < start:
        raise ValueError("end_date deve ser maior ou igual a start_date")
    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    if not dates:
        raise ValueError("Nenhum dia útil no intervalo informado")
    return dates


def _resolve_benchmark(ticker: str) -> str:
    benchmark_map = DEFAULT_CONFIG.get("benchmark_map", {}) or {}
    ticker_upper = ticker.upper()
    for suffix, benchmark in benchmark_map.items():
        if suffix and ticker_upper.endswith(suffix.upper()):
            return benchmark
    return benchmark_map.get("", "SPY")


def _compute_realized_return(ticker: str, trade_date: str, holding_days: int) -> tuple:
    """Mirrors ``TradingAgentsGraph._fetch_returns`` (same formula/benchmark
    map). Not called through a graph instance: building one just for this
    calculation would pay the cost of constructing LLM clients for no
    benefit, since this only needs price history.
    """
    benchmark = _resolve_benchmark(ticker)
    try:
        start = datetime.strptime(trade_date, "%Y-%m-%d")
        end = start + timedelta(days=holding_days + 7)
        end_str = end.strftime("%Y-%m-%d")
        stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
        bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)
        if len(stock) <= holding_days or len(bench) <= holding_days:
            return None, None, None, None, benchmark
        raw = float((stock["Close"].iloc[holding_days] - stock["Close"].iloc[0]) / stock["Close"].iloc[0])
        bench_ret = float((bench["Close"].iloc[holding_days] - bench["Close"].iloc[0]) / bench["Close"].iloc[0])
        alpha = raw - bench_ret
        resolution_date = stock.index[holding_days].strftime("%Y-%m-%d")
        return raw, alpha, holding_days, resolution_date, benchmark
    except Exception:
        return None, None, None, None, benchmark


class BacktestService:
    def __init__(self, adapter, run_lock: asyncio.Lock):
        self.adapter = adapter
        self.run_lock = run_lock

    def create_job(self, symbol: str, start_date: str, end_date: str, holding_days: int) -> dict[str, Any]:
        dates = _business_dates(start_date, end_date)
        if holding_days <= 0:
            raise ValueError("holding_days deve ser positivo")
        job_id = uuid.uuid4().hex[:8]
        db.create_backtest_job({
            "id": job_id, "symbol": symbol.upper(), "start_date": start_date, "end_date": end_date,
            "holding_days": holding_days, "status": "QUEUED",
            "created_at": datetime.now(timezone.utc).isoformat(), "total_dates": len(dates),
        })
        return db.get_backtest_job(job_id)

    def request_cancel(self, job_id: str) -> None:
        db.update_backtest_job(job_id, cancel_requested=1)

    async def run_job(self, job_id: str) -> None:
        job = db.get_backtest_job(job_id)
        if not job:
            return
        db.update_backtest_job(job_id, status="RUNNING")
        dates = _business_dates(job["start_date"], job["end_date"])
        completed = 0
        for trade_date in dates:
            fresh = db.get_backtest_job(job_id)
            if fresh and fresh.get("cancel_requested"):
                db.update_backtest_job(job_id, status="CANCELLED")
                return
            db.update_backtest_job(job_id, current_date=trade_date)
            run_id = f"{job_id}-{trade_date}"
            started_at = datetime.now(timezone.utc).isoformat()
            db.upsert_run({
                "id": run_id, "kind": "backtest", "backtest_job_id": job_id, "symbol": job["symbol"],
                "trade_date": trade_date, "status": "RUNNING", "started_at": started_at, "logs": [],
            })

            def add_event(event: dict, _date=trade_date) -> None:
                print(f"[backtest {job_id} {_date}] [{event.get('kind', 'evento')}] {event.get('text', '')}", flush=True)

            def on_pid(pid: int, _run_id=run_id) -> None:
                db.upsert_run({"id": _run_id, "pid": pid})

            async with self.run_lock:
                try:
                    result = await self.adapter.analyze(job["symbol"], None, None, add_event, trade_date=trade_date, on_pid=on_pid)
                except Exception as exc:
                    db.upsert_run({"id": run_id, "status": "ERROR", "error": str(exc), "finished_at": datetime.now(timezone.utc).isoformat()})
                    completed += 1
                    db.update_backtest_job(job_id, completed_dates=completed)
                    continue

            status = "INCONCLUSIVE" if result.get("is_review") else "COMPLETED"
            raw_return, alpha_return, holding, resolution_date, benchmark = await asyncio.to_thread(
                _compute_realized_return, job["symbol"], trade_date, job["holding_days"]
            )
            db.upsert_run({
                "id": run_id, "status": status, "decision": result.get("decision"), "rating_5tier": result.get("rating_5tier"),
                "summary": result.get("summary"), "model": result.get("model"), "provider": result.get("provider"),
                "finished_at": datetime.now(timezone.utc).isoformat(), "raw_return": raw_return, "alpha_return": alpha_return,
                "benchmark": benchmark, "holding_days": holding, "resolution_date": resolution_date,
            })
            completed += 1
            db.update_backtest_job(job_id, completed_dates=completed)
        db.update_backtest_job(job_id, status="DONE", current_date=None)
