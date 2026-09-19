from datetime import datetime, timezone
import asyncio
import threading
import time
import httpx
from typing import Any
from ..llm.ollama import OllamaProvider
from ..config import settings
from langchain_core.callbacks import BaseCallbackHandler

AGENTS = ["Market Analyst", "Fundamental Analyst", "News Analyst", "Sentiment Analyst", "Bull Researcher", "Bear Researcher", "Trader", "Risk Engine"]

class TradingAgentsAdapter:
    def __init__(self, ollama: OllamaProvider, default_model: str = "qwen2.5:3b"):
        self.ollama = ollama
        self.default_model = default_model
        self._graph = None

    def _get_graph(self, model: str, events=None):
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        # The upstream LLM may emit the user-facing B3 ticker (PETR4) when
        # invoking a data tool. Normalize that call at the adapter boundary.
        import re
        from tradingagents.dataflows import y_finance, stockstats_utils
        original_normalize = y_finance.normalize_symbol
        original_stock_data = y_finance.get_YFin_data_online
        def normalize_for_app(value):
            text = str(value).upper().strip()
            return f"{text}.SA" if re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", text) else original_normalize(value)
        y_finance.normalize_symbol = normalize_for_app
        stockstats_utils.normalize_symbol = normalize_for_app
        def stock_data_with_date_alias(symbol, start_date, end_date):
            # Ollama sometimes emits natural-language aliases even though the
            # upstream tool schema requires strict YYYY-MM-DD dates.
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if str(end_date).strip().lower() in {"now", "today", "current", "hoje"}:
                end_date = today
            if str(start_date).strip().lower() in {"now", "today", "current", "hoje"}:
                start_date = today
            return original_stock_data(symbol, start_date, end_date)
        y_finance.get_YFin_data_online = stock_data_with_date_alias
        # The upstream vendor registry keeps the original function object;
        # replace that entry too so the wrapper is actually used by the tool.
        from tradingagents.dataflows import interface as data_interface
        data_interface.VENDOR_METHODS["get_stock_data"]["yfinance"] = stock_data_with_date_alias
        if not hasattr(data_interface, "_app_original_route_to_vendor"):
            data_interface._app_original_route_to_vendor = data_interface.route_to_vendor
        original_route = data_interface._app_original_route_to_vendor
        def route_with_events(method, *args, **kwargs):
            started = time.perf_counter()
            if events:
                safe_args = ", ".join(str(value)[:100] for value in args)
                events({"kind": "tool_request", "text": f"TradingAgents chamou {method}({safe_args})"})
            try:
                output = original_route(method, *args, **kwargs)
            except Exception as exc:
                if events:
                    cause = exc.__cause__ or exc.__context__
                    detail = f"{type(exc).__name__}: {exc}"
                    if cause:
                        detail += f" <- {type(cause).__name__}: {cause}"
                    events({"kind": "tool_error", "text": f"{method} falhou após {time.perf_counter() - started:.2f}s · {detail}"})
                raise
            if events:
                summary = str(output).replace("\r", " ").replace("\n", " ")
                summary = summary[:900] + ("..." if len(summary) > 900 else "")
                events({"kind": "tool_response", "text": f"{method} respondeu em {time.perf_counter() - started:.2f}s · {summary}"})
            return output
        data_interface.route_to_vendor = route_with_events
        from tradingagents.agents.utils import (
            core_stock_tools, fundamental_data_tools, macro_data_tools,
            news_data_tools, prediction_markets_tools, technical_indicators_tools,
        )
        for tool_module in (core_stock_tools, fundamental_data_tools, macro_data_tools, news_data_tools, prediction_markets_tools, technical_indicators_tools):
            tool_module.route_to_vendor = route_with_events
        config = DEFAULT_CONFIG.copy()
        local_state = "data/tradingagents"
        config.update({"llm_provider": "ollama", "deep_think_llm": model, "quick_think_llm": model, "backend_url": f"{settings.ollama_base_url.rstrip('/')}/v1", "project_dir": local_state, "data_cache_dir": f"{local_state}/cache", "results_dir": f"{local_state}/results", "memory_log_path": f"{local_state}/memory.md", "max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "llm_max_retries": 0, "news_article_limit": 5, "global_news_article_limit": 3, "output_language": "Portuguese"})
        class EventHandler(BaseCallbackHandler):
            def _emit(self, kind, text):
                if events is not None: events({"kind": kind, "text": text})
            def on_chain_start(self, serialized, inputs, **kwargs): self._emit("agent_start", (serialized or {}).get("name", "LangGraph chain"))
            def on_tool_start(self, serialized, input_str, **kwargs): self._emit("tool", (serialized or {}).get("name", "market tool"))
            def on_chain_end(self, outputs, **kwargs): self._emit("agent_end", "step finished")
            def on_tool_end(self, output, **kwargs):
                text = str(output).replace("\n", " ")
                self._emit("tool_end", f"Resposta externa: {text[:700]}{'...' if len(text) > 700 else ''}")
            def on_tool_error(self, error, **kwargs): self._emit("tool_error", f"Ferramenta externa falhou: {error}")
            def on_chain_error(self, error, **kwargs): self._emit("error", str(error))
        selected_analysts = ("market", "news", "fundamentals")
        if events: events({"kind": "config", "text": "Analistas sociais pausados para evitar bloqueio de Reddit/StockTwits"})
        return TradingAgentsGraph(selected_analysts=selected_analysts, debug=True, config=config, callbacks=[EventHandler()] if events else None)

    async def analyze(self, symbol: str, model: str | None = None, quote: dict[str, Any] | None = None, events=None) -> dict[str, Any]:
        upstream_symbol = symbol.upper().strip()
        if upstream_symbol.endswith(".SA") is False and upstream_symbol.isalnum():
            upstream_symbol = f"{upstream_symbol}.SA"
        models = await self.ollama.list_models()
        available = {item.get("name") for item in models}
        selected = model or (self.default_model if self.default_model in available else (models[0].get("name") if models else None))
        if not selected:
            raise RuntimeError("Nenhum modelo Ollama disponível")
        if events: events({"kind": "run", "text": f"TradingAgentsGraph iniciado para {symbol.upper()} com {selected}"})
        graph = self._get_graph(selected, events)
        if events: events({"kind": "market", "text": f"Ticker normalizado para o upstream: {upstream_symbol}"})
        if events: events({"kind": "graph", "text": "Grafo LangGraph executando os agentes e ferramentas"})
        stop_monitor = threading.Event()
        def monitor():
            last_status = None
            while not stop_monitor.wait(3):
                try:
                    with httpx.Client(timeout=2) as client:
                        running = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/ps").json().get("models", [])
                    if running:
                        model_info = running[0]
                        status = (model_info.get('name'), model_info.get('size_vram'), model_info.get('size'))
                        if status != last_status:
                            events({"kind": "ollama", "text": f"Ollama ativo: {model_info.get('name')} · VRAM {round(model_info.get('size_vram', 0)/1024/1024/1024, 2)} GB"})
                            last_status = status
                    else:
                        if last_status != "idle":
                            events({"kind": "wait", "text": "Ollama sem modelo ativo; aguardando ferramenta/dados de mercado"})
                            last_status = "idle"
                except Exception as exc:
                    status = f"error:{exc}"
                    if status != last_status:
                        events({"kind": "monitor", "text": f"Monitor Ollama: {exc}"})
                        last_status = status
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            try:
                _, decision = await asyncio.wait_for(asyncio.to_thread(graph.propagate, upstream_symbol, datetime.now(timezone.utc).strftime("%Y-%m-%d")), timeout=180)
            except asyncio.TimeoutError as exc:
                if events: events({"kind": "timeout", "text": "Análise interrompida após 180s; uma ferramenta externa não respondeu"})
                raise RuntimeError("TradingAgents excedeu o limite de 180 segundos. Verifique Yahoo Finance ou outra fonte externa.") from exc
            except Exception as exc:
                if events: events({"kind": "error", "text": f"TradingAgents falhou: {type(exc).__name__}: {exc}"})
                raise
        finally:
            stop_monitor.set()
        decision_text = str(decision)
        normalized = "SELL" if "SELL" in decision_text.upper() else "HOLD" if "HOLD" in decision_text.upper() else "BUY"
        if events: events({"kind": "complete", "text": f"Decisão final recebida: {normalized}"})
        return {"symbol": symbol.upper(), "timestamp": datetime.now(timezone.utc).isoformat(), "provider": "ollama", "model": selected, "decision": normalized, "confidence": 0.0, "summary": decision_text, "source": "TradingAgentsGraph", "agents": [{"name": name, "status": "FINISHED", "decision": "SEE REPORT", "confidence": 0.0} for name in AGENTS]}

        # Kept below as a fallback reference for development; the production path above is upstream.
        summary = "Nenhum modelo Ollama disponível; análise demonstrativa ativada."
        if selected:
            try:
                result = await self.ollama.generate(selected, f"Analise {symbol} para paper trading usando estes dados reais: {quote or {}}. Responda em uma frase com tendência e riscos.")
                summary = result.get("response", "").strip() or summary
            except Exception as exc:
                summary = f"Ollama indisponível durante a análise: {exc}"
        return {"symbol": symbol.upper(), "timestamp": datetime.now(timezone.utc).isoformat(), "provider": "ollama" if selected else "none", "model": selected or "none", "decision": "BUY", "confidence": 0.74, "summary": summary, "agents": [{"name": name, "status": "FINISHED", "decision": "BULLISH" if i < 4 else ("BUY" if i == 4 else "HOLD"), "confidence": max(0.61, 0.84 - i * 0.03)} for i, name in enumerate(AGENTS)]}
