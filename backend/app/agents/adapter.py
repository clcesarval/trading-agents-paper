from datetime import datetime, timezone
from typing import Any
from ..llm.ollama import OllamaProvider
from ..config import settings
from ..execution.runner import run_isolated, AnalysisTimeout, AnalysisFailed, AnalysisCancelled
from ..execution.portfolio_forced import format_historical_rating_note
from ..storage import db

AGENTS = ["Market Analyst", "Sentiment Analyst", "Fundamental Analyst", "News Analyst", "Bull Researcher", "Bear Researcher", "Trader", "Risk Engine", "Portfolio Manager"]

# 5-tier upstream rating -> the simple BUY/SELL/HOLD badge the UI shows.
# Derived, never invented: a rating outside this map (i.e. REVIEW) never
# reaches here — callers must check ``is_review`` first (#1170 upstream).
_RATING_TO_SIMPLE = {
    "Buy": "BUY", "Overweight": "BUY",
    "Hold": "HOLD",
    "Underweight": "SELL", "Sell": "SELL",
}


class TradingAgentsAdapter:
    def __init__(self, ollama: OllamaProvider, default_model: str = "qwen2.5:3b"):
        self.ollama = ollama
        self.default_model = default_model

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        upstream_symbol = symbol.upper().strip()
        if not upstream_symbol.endswith(".SA") and upstream_symbol.isalnum():
            upstream_symbol = f"{upstream_symbol}.SA"
        return upstream_symbol

    async def analyze(self, symbol: str, model: str | None = None, quote: dict[str, Any] | None = None, events=None, trade_date: str | None = None, on_pid=None, cancel_check=None) -> dict[str, Any]:
        upstream_symbol = self.normalize_symbol(symbol)
        provider = settings.llm_provider or "ollama"
        if provider == "ollama":
            models = await self.ollama.list_models()
            available = {item.get("name") for item in models}
            selected = model or (self.default_model if self.default_model in available else (models[0].get("name") if models else None))
            if not selected:
                raise RuntimeError("Nenhum modelo Ollama disponível")
        else:
            # Non-local provider (e.g. Gemini's free tier, used to test this
            # pipeline against a model with more reliable structured-output
            # support than the small local models that broke it) — no Ollama
            # model list to check against, just the configured model name.
            selected = model or settings.llm_model
            if not selected:
                raise RuntimeError(f"Nenhum modelo configurado para o provider '{provider}' (defina LLM_MODEL no .env)")
        if events: events({"kind": "run", "text": f"Preparando execução isolada para {symbol.upper()} com {selected} ({provider})"})
        if events: events({"kind": "market", "text": f"Ticker normalizado para o upstream: {upstream_symbol}"})

        local_state = "data/tradingagents"
        # db.rating_distribution looks up by the plain ticker as stored in
        # the runs table (backend/app/backtest/service.py writes
        # symbol.upper(), never the upstream-normalized ".SA" form) — using
        # upstream_symbol here would silently match nothing.
        historical_rating_note = format_historical_rating_note(db.rating_distribution(symbol.upper()))
        payload = {
            "symbol": upstream_symbol,
            "model": selected,
            "provider": provider,
            "ollama_base_url": settings.ollama_base_url,
            "google_api_key": settings.google_api_key,
            "nvidia_api_key": settings.nvidia_api_key,
            "openai_api_key": settings.openai_api_key,
            "historical_rating_note": historical_rating_note,
            "reasoning_effort": settings.llm_reasoning_effort,
            "grounded_market_analyst": settings.grounded_market_analyst,
            "consistent_portfolio_manager": settings.consistent_portfolio_manager,
            "temperature": settings.llm_temperature,
            "trade_date": trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "project_dir": local_state,
            "data_cache_dir": f"{local_state}/cache",
            "results_dir": f"{local_state}/results",
            "memory_log_path": f"{local_state}/memory.md",
        }

        def forward_event(event: dict) -> None:
            if events:
                events(event)

        try:
            final = await run_isolated(payload, forward_event, float(settings.analysis_timeout_seconds), on_start=on_pid, cancel_check=cancel_check)
        except AnalysisCancelled:
            if events: events({"kind": "config", "text": "Análise cancelada pelo usuário; processo encerrado."})
            raise
        except AnalysisTimeout as exc:
            if events: events({"kind": "timeout", "text": str(exc)})
            raise RuntimeError(str(exc)) from exc
        except AnalysisFailed as exc:
            if events:
                events({"kind": "error", "text": f"TradingAgents falhou: {exc}"})
                if exc.traceback_text:
                    events({"kind": "traceback", "text": exc.traceback_text})
            raise RuntimeError(str(exc)) from exc

        signal = final["signal"]
        is_review = bool(final["is_review"])
        decision_text = final.get("decision_text", "")
        simple_decision = None if is_review else _RATING_TO_SIMPLE.get(signal)

        return {
            "symbol": symbol.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": selected,
            "decision": simple_decision,
            "rating_5tier": signal,
            "is_review": is_review,
            "confidence": None,
            "summary": decision_text,
            "source": "TradingAgentsGraph",
            "agents": [{"name": name, "status": "FINISHED"} for name in AGENTS],
        }
