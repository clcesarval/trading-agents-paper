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

from ..execution.runner import AnalysisCancelled
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
        """Run every date in the job's range, skipping ones a previous attempt
        already resolved (COMPLETED/INCONCLUSIVE). Calling this again on a job
        that errored or was cancelled therefore retries only what's left,
        instead of re-running the (expensive, minutes-long) pipeline for dates
        that already have a real decision.
        """
        job = db.get_backtest_job(job_id)
        if not job:
            return
        dates = _business_dates(job["start_date"], job["end_date"])
        prior_runs = {r["trade_date"]: r for r in db.list_runs(kind="backtest", backtest_job_id=job_id)}
        resolved_statuses = {"COMPLETED", "INCONCLUSIVE"}
        completed_ok = sum(1 for d in dates if prior_runs.get(d, {}).get("status") in resolved_statuses)
        completed = completed_ok
        db.update_backtest_job(job_id, status="RUNNING", cancel_requested=0, error=None, total_dates=len(dates), completed_dates=completed)
        for trade_date in dates:
            if prior_runs.get(trade_date, {}).get("status") in resolved_statuses:
                continue
            fresh = db.get_backtest_job(job_id)
            if fresh and fresh.get("cancel_requested"):
                db.update_backtest_job(job_id, status="CANCELLED")
                return
            run_id = f"{job_id}-{trade_date}"
            # A retry reuses this same run_id for a date whose previous attempt
            # errored, so every terminal field from that attempt must be reset
            # here — otherwise a stale finished_at survives next to a fresh
            # started_at and duration_seconds comes out negative (#1 reported
            # live: "-811s").
            db.upsert_run({
                "id": run_id, "kind": "backtest", "backtest_job_id": job_id, "symbol": job["symbol"],
                "trade_date": trade_date, "status": "QUEUED", "logs": [], "started_at": None, "finished_at": None,
                "error": None, "decision": None, "rating_5tier": None, "summary": None, "raw_return": None,
                "alpha_return": None, "benchmark": None, "holding_days": None, "resolution_date": None, "pid": None,
            })
            date_logs: list[dict] = []

            def add_event(event: dict, _date=trade_date, _run_id=run_id) -> None:
                print(f"[backtest {job_id} {_date}] [{event.get('kind', 'evento')}] {event.get('text', '')}", flush=True)
                date_logs.append({**event, "timestamp": datetime.now(timezone.utc).isoformat()})
                del date_logs[:-200]
                db.upsert_run({"id": _run_id, "logs": list(date_logs)})

            def on_pid(pid: int, _run_id=run_id) -> None:
                db.upsert_run({"id": _run_id, "pid": pid})

            # Status/current_date only flip to RUNNING once the shared
            # execution slot is actually acquired — a queued date must never
            # be reported as running while it's still waiting behind a live
            # analysis or an earlier backtest date.
            def cancel_check(_job_id=job_id) -> bool:
                current = db.get_backtest_job(_job_id)
                return bool(current and current.get("cancel_requested"))

            async with self.run_lock:
                db.update_backtest_job(job_id, current_date=trade_date)
                db.upsert_run({"id": run_id, "status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat()})
                try:
                    result = await self.adapter.analyze(
                        job["symbol"], None, None, add_event, trade_date=trade_date, on_pid=on_pid, cancel_check=cancel_check,
                    )
                except AnalysisCancelled:
                    # Cancel takes effect immediately (the in-flight process is
                    # killed by run_isolated), not just after this date happens
                    # to finish on its own.
                    db.upsert_run({"id": run_id, "status": "CANCELLED", "finished_at": datetime.now(timezone.utc).isoformat()})
                    db.update_backtest_job(job_id, status="CANCELLED", current_date=None)
                    return
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
            completed_ok += 1
            db.update_backtest_job(job_id, completed_dates=completed)
        if completed_ok == 0:
            # Every date processed ended in error (e.g. all timed out) — "DONE"
            # would read as success next to a table full of ERROR rows (#1
            # reported live: a 1-day job showing CONCLUÍDO with its only date
            # in ERROR). Report it as ERROR so the badge matches the table.
            db.update_backtest_job(
                job_id, status="ERROR", current_date=None,
                error="Nenhuma data foi concluída com sucesso — veja o motivo na tabela por data.",
            )
        else:
            db.update_backtest_job(job_id, status="DONE", current_date=None)
