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
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.default_config import DEFAULT_CONFIG

from ..execution.runner import AnalysisCancelled
from ..execution.worker import is_b3_ticker, to_b3_ticker
from .. import power
from ..analysis.confidence import assess_confidence
from ..analysis.consensus import summarize_consensus
from ..storage import db

# Real case that motivated this: PETR4 2026-08-17 came back Buy, Hold, Hold and
# Buy across four separate attempts at the same date — a single run's verbal
# confidence does not catch that instability. A hard cap keeps an accidental
# high number from turning one backtest date into an hour-long re-run.
MAX_CONSENSUS_RUNS = 5


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


def _price_ticker(ticker: str) -> str:
    # Upstream's normalize_symbol leaves a bare B3 code ("PETR4") untouched, so
    # Yahoo answers 404 and the return silently came back empty. The .SA suffix
    # is otherwise only applied inside the worker process.
    return to_b3_ticker(ticker) if is_b3_ticker(ticker) else normalize_symbol(ticker)


def _resolve_benchmark(ticker: str) -> str:
    ticker_upper = _price_ticker(ticker).upper()
    # Upstream's benchmark_map has no B3 entry, so a Brazilian stock fell back
    # to SPY; the meaningful yardstick is the Ibovespa.
    if ticker_upper.endswith(".SA"):
        return "^BVSP"
    benchmark_map = DEFAULT_CONFIG.get("benchmark_map", {}) or {}
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
        # holding_days counts trading days; leave room for weekends/holidays.
        end = start + timedelta(days=holding_days * 2 + 7)
        end_str = end.strftime("%Y-%m-%d")
        stock = yf.Ticker(_price_ticker(ticker)).history(start=trade_date, end=end_str)
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


def _reference_close(ticker: str, trade_date: str) -> float | None:
    """Real closing price on (or just before) the analysis date, to check the
    price levels the model cites. None if Yahoo has nothing."""
    try:
        end = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=1)
        start = end - timedelta(days=12)
        hist = yf.Ticker(_price_ticker(ticker)).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        return float(hist["Close"].iloc[-1]) if len(hist) else None
    except Exception:
        return None


async def _confidence_columns(symbol: str, trade_date: str, events: list[dict]) -> dict[str, Any]:
    close = await asyncio.to_thread(_reference_close, symbol, trade_date)
    result = assess_confidence(events, trade_date, close)
    return {"confidence_pct": result["pct"], "confidence_json": json.dumps(result, ensure_ascii=False)}


class BacktestService:
    def __init__(self, adapter, run_lock: asyncio.Lock):
        self.adapter = adapter
        self.run_lock = run_lock

    def create_job(self, symbol: str, start_date: str, end_date: str, holding_days: int, consensus_runs: int = 1) -> dict[str, Any]:
        dates = _business_dates(start_date, end_date)
        if holding_days <= 0:
            raise ValueError("holding_days deve ser positivo")
        consensus_runs = max(1, min(int(consensus_runs or 1), MAX_CONSENSUS_RUNS))
        job_id = uuid.uuid4().hex[:8]
        db.create_backtest_job({
            "id": job_id, "symbol": symbol.upper(), "start_date": start_date, "end_date": end_date,
            "holding_days": holding_days, "status": "QUEUED", "consensus_runs": consensus_runs,
            "created_at": datetime.now(timezone.utc).isoformat(), "total_dates": len(dates),
        })
        return db.get_backtest_job(job_id)

    def request_cancel(self, job_id: str) -> None:
        db.update_backtest_job(job_id, cancel_requested=1)

    def reset_date(self, job_id: str, trade_date: str) -> None:
        """Force one date back to QUEUED so the next ``run_job`` call redoes
        it, even if it already has a real (COMPLETED/INCONCLUSIVE) outcome —
        e.g. a date that only ever came back INCONCLUSIVE (REVIEW) and the
        user wants another attempt at a real decision, not just the dates
        that errored out.
        """
        run_id = f"{job_id}-{trade_date}"
        db.upsert_run({
            "id": run_id, "status": "QUEUED", "logs": [], "started_at": None, "finished_at": None,
            "error": None, "decision": None, "rating_5tier": None, "summary": None, "raw_return": None,
            "alpha_return": None, "benchmark": None, "holding_days": None, "resolution_date": None, "pid": None,
            "confidence_pct": None, "confidence_json": None, "consensus_json": None,
        })

    async def recompute_confidence(self, job_id: str) -> int:
        """Re-score every finished run of a job from its stored events (no AI is
        re-run). Returns how many runs were scored."""
        job = db.get_backtest_job(job_id)
        if not job:
            return 0
        count = 0
        for run in db.list_runs(kind="backtest", backtest_job_id=job_id):
            if run.get("status") in ("COMPLETED", "INCONCLUSIVE") and run.get("logs"):
                db.upsert_run({"id": run["id"], **await _confidence_columns(job["symbol"], run["trade_date"], run["logs"])})
                count += 1
        return count

    async def run_job(self, job_id: str) -> None:
        # Held for the whole job (including waits between dates) so Windows'
        # idle timer cannot suspend the PC in the middle of a multi-hour run.
        with power.keep_awake():
            await self._run_job(job_id)

    async def _run_job(self, job_id: str) -> None:
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
            prior = prior_runs.get(trade_date, {})
            if prior.get("status") in resolved_statuses:
                # Decision already exists; only the price-based score may be missing
                # (e.g. it failed at the time). Fill it in without re-running the AI.
                if prior.get("raw_return") is None:
                    raw_return, alpha_return, holding, resolution_date, benchmark = await asyncio.to_thread(
                        _compute_realized_return, job["symbol"], trade_date, job["holding_days"]
                    )
                    if raw_return is not None:
                        db.upsert_run({
                            "id": prior["id"], "raw_return": raw_return, "alpha_return": alpha_return,
                            "benchmark": benchmark, "holding_days": holding, "resolution_date": resolution_date,
                        })
                if prior.get("confidence_pct") is None and prior.get("logs"):
                    db.upsert_run({"id": prior["id"], **await _confidence_columns(job["symbol"], trade_date, prior["logs"])})
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
            # Research on LLM trading agents (FINSABER/TradeTrap) finds that a
            # single run's verbal confidence barely predicts whether its
            # decision is reliable — the same date can flip between attempts
            # (seen live: PETR4 2026-08-17 came back Buy, Hold, Hold, Buy across
            # four separate runs). consensus_runs > 1 re-runs the whole pipeline
            # for this date and votes on the outcome instead of trusting one
            # attempt; consensus_runs == 1 (the default) behaves exactly as
            # before — one attempt, its own decision and confidence stand as-is.
            consensus_runs = max(1, min(int(job.get("consensus_runs") or 1), MAX_CONSENSUS_RUNS))
            combined_logs: list[dict] = []
            attempts_summary: list[dict[str, Any]] = []
            cancelled = False
            last_error: str | None = None

            db.upsert_run({"id": run_id, "status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat()})

            for attempt in range(1, consensus_runs + 1):
                attempt_logs: list[dict] = []

                def add_event(event: dict, _date=trade_date, _run_id=run_id, _attempt_logs=attempt_logs) -> None:
                    print(f"[backtest {job_id} {_date}] [{event.get('kind', 'evento')}] {event.get('text', '')}", flush=True)
                    stamped = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}
                    _attempt_logs.append(stamped)
                    combined_logs.append(stamped)
                    # 200 was too small: the 30s heartbeats push the early data-fetch
                    # events out, which made the confidence audit report missing data.
                    del combined_logs[:-2000]
                    db.upsert_run({"id": _run_id, "logs": list(combined_logs)})

                def on_pid(pid: int, _run_id=run_id) -> None:
                    db.upsert_run({"id": _run_id, "pid": pid})

                # Status/current_date only flip to RUNNING once the shared
                # execution slot is actually acquired — a queued date must never
                # be reported as running while it's still waiting behind a live
                # analysis or an earlier backtest date.
                def cancel_check(_job_id=job_id) -> bool:
                    current = db.get_backtest_job(_job_id)
                    return bool(current and current.get("cancel_requested"))

                if consensus_runs > 1:
                    add_event({"kind": "config", "text": f"Consenso entre execuções: rodando tentativa {attempt} de {consensus_runs} para {trade_date}."})

                async with self.run_lock:
                    fresh = db.get_backtest_job(job_id)
                    if fresh and fresh.get("cancel_requested"):
                        cancelled = True
                        break
                    db.update_backtest_job(job_id, current_date=trade_date)
                    try:
                        result = await self.adapter.analyze(
                            job["symbol"], None, None, add_event, trade_date=trade_date, on_pid=on_pid, cancel_check=cancel_check,
                        )
                    except AnalysisCancelled:
                        # Cancel takes effect immediately (the in-flight process is
                        # killed by run_isolated), not just after this date happens
                        # to finish on its own.
                        cancelled = True
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        attempts_summary.append({"ok": False, "decision": None, "confidence_pct": None})
                        continue

                confidence = await _confidence_columns(job["symbol"], trade_date, attempt_logs)
                attempts_summary.append({
                    "ok": True, "decision": result.get("decision"), "confidence_pct": confidence.get("confidence_pct"),
                    "rating_5tier": result.get("rating_5tier"), "is_review": result.get("is_review"),
                    "model": result.get("model"), "provider": result.get("provider"), "summary": result.get("summary"),
                    "confidence_json": confidence.get("confidence_json"),
                })

            if cancelled:
                db.upsert_run({"id": run_id, "status": "CANCELLED", "finished_at": datetime.now(timezone.utc).isoformat()})
                db.update_backtest_job(job_id, status="CANCELLED", current_date=None)
                return

            ok_attempts = [a for a in attempts_summary if a["ok"]]
            if not ok_attempts:
                db.upsert_run({
                    "id": run_id, "status": "ERROR",
                    "error": last_error or "Todas as tentativas falharam",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                })
                completed += 1
                db.update_backtest_job(job_id, completed_dates=completed)
                continue

            consensus = summarize_consensus(ok_attempts)
            has_majority = consensus["decision"] is not None
            representative = (
                next(a for a in ok_attempts if a["decision"] == consensus["decision"]) if has_majority else ok_attempts[-1]
            )
            status = "COMPLETED" if has_majority else "INCONCLUSIVE"
            if consensus_runs == 1:
                rating_5tier = representative["rating_5tier"]  # unchanged wording from a single attempt
            elif has_majority:
                votes_for_winner = consensus["votes"].get(consensus["decision"], 0)
                rating_5tier = f"{representative['rating_5tier']} (consenso {votes_for_winner}/{consensus['runs']})"
            else:
                votes_txt = " / ".join(f"{label}: {count}" for label, count in consensus["votes"].items())
                rating_5tier = f"Sem consenso ({votes_txt})"

            confidence_detail = json.loads(representative["confidence_json"]) if representative.get("confidence_json") else None
            confidence_pct = representative["confidence_pct"] if consensus_runs == 1 else consensus["confidence_pct"]
            consensus_json = None
            if consensus_runs > 1:
                consensus_json = json.dumps(consensus, ensure_ascii=False)
                if confidence_detail is not None:
                    confidence_detail = {**confidence_detail, "consensus": consensus}
            confidence_json = json.dumps(confidence_detail, ensure_ascii=False) if confidence_detail is not None else None

            raw_return, alpha_return, holding, resolution_date, benchmark = await asyncio.to_thread(
                _compute_realized_return, job["symbol"], trade_date, job["holding_days"]
            )
            db.upsert_run({
                "id": run_id, "status": status, "decision": consensus["decision"], "rating_5tier": rating_5tier,
                "summary": representative.get("summary"), "model": representative.get("model"), "provider": representative.get("provider"),
                "finished_at": datetime.now(timezone.utc).isoformat(), "raw_return": raw_return, "alpha_return": alpha_return,
                "benchmark": benchmark, "holding_days": holding, "resolution_date": resolution_date,
                "confidence_pct": confidence_pct, "confidence_json": confidence_json, "consensus_json": consensus_json,
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
