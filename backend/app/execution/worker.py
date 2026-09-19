"""Entry point that runs inside the isolated analysis process.

Runs in its own OS process (multiprocessing, spawn) so the parent can
actually kill it on timeout — a thread cannot be forcibly stopped once it is
blocked inside a synchronous upstream call like ``graph.propagate()``. All
communication with the parent happens through ``queue``; this module must
never import ``backend.app.main`` (that would pull in FastAPI/uvicorn state
that has no business existing in a child process).
"""
from __future__ import annotations

import logging
import re
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

DATE_ALIASES = {"now", "today", "current", "hoje"}
_B3_TICKER_RE = re.compile(r"[A-Z]{4}[0-9]{1,2}")


def is_b3_ticker(value: str) -> bool:
    return bool(_B3_TICKER_RE.fullmatch(str(value).upper().strip()))


def to_b3_ticker(value: str) -> str:
    return f"{str(value).upper().strip()}.SA"


def resolve_date_alias(value: str, today: str) -> str:
    """LLM tool calls sometimes emit ``now``/``today``/``hoje``/``current``
    even though the upstream tool schema requires a strict YYYY-MM-DD date."""
    return today if str(value).strip().lower() in DATE_ALIASES else value


def clamp_future_date(value: str, as_of: str) -> str:
    """Cap a tool-call date at ``as_of`` (the run's own trade date).

    A small local model occasionally invents a plausible-looking but wrong
    end_date (e.g. asking for data far in the future) instead of the actual
    as-of date. Yahoo Finance then has no rows that recent and the upstream
    staleness guard raises NoMarketDataError, killing the whole analysis over
    a tool-call typo. Any ISO date past ``as_of`` is clamped back to it; a
    malformed value is left untouched so the underlying call can raise its
    own, clearer error instead of this helper masking it.
    """
    try:
        return value if value <= as_of else as_of
    except TypeError:
        return value


def _emit(queue, kind: str, text: str) -> None:
    try:
        queue.put({"kind": kind, "text": text, "ts": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass


def _install_monkeypatches(events_emit, as_of_date: str):
    """Mirror the upstream-facing fixes previously in adapter.py, now inside
    the worker process: B3 ticker normalization, natural-language date
    aliases from the LLM, and per-tool-call event instrumentation.

    ``as_of_date`` is the run's own trade date (today for a live analysis,
    the historical date for a backtest day) — never the real wall clock, so a
    backtest never resolves "today" to a date after the one it is simulating.
    """
    from tradingagents.dataflows import y_finance, stockstats_utils
    from tradingagents.dataflows import interface as data_interface

    original_normalize = y_finance.normalize_symbol
    original_stock_data = y_finance.get_YFin_data_online

    def normalize_for_app(value):
        return to_b3_ticker(value) if is_b3_ticker(value) else original_normalize(value)

    y_finance.normalize_symbol = normalize_for_app
    stockstats_utils.normalize_symbol = normalize_for_app

    def stock_data_with_date_alias(symbol, start_date, end_date):
        clamped_start = clamp_future_date(resolve_date_alias(start_date, as_of_date), as_of_date)
        resolved_end = resolve_date_alias(end_date, as_of_date)
        clamped_end = clamp_future_date(resolved_end, as_of_date)
        if clamped_end != resolved_end:
            events_emit(
                "config",
                f"get_stock_data pediu dados até {resolved_end}, além da data desta análise "
                f"({as_of_date}); ajustado para {clamped_end} em vez de falhar a análise.",
            )
        return original_stock_data(symbol, clamped_start, clamped_end)

    y_finance.get_YFin_data_online = stock_data_with_date_alias
    data_interface.VENDOR_METHODS["get_stock_data"]["yfinance"] = stock_data_with_date_alias

    original_route = data_interface.route_to_vendor

    def _redact(value) -> str:
        text = str(value)
        if re.search(r"(key|token|secret|password|apikey)", text, re.IGNORECASE) and len(text) > 12:
            return "[redacted]"
        return text[:100]

    def route_with_events(method, *args, **kwargs):
        started = time.perf_counter()
        safe_args = ", ".join(_redact(value) for value in args)
        events_emit("tool_request", f"TradingAgents chamou {method}({safe_args})")
        try:
            output = original_route(method, *args, **kwargs)
        except Exception as exc:
            cause = exc.__cause__ or exc.__context__
            detail = f"{type(exc).__name__}: {exc}"
            if cause:
                detail += f" <- {type(cause).__name__}: {cause}"
            events_emit("tool_error", f"{method} falhou após {time.perf_counter() - started:.2f}s · {detail}")
            raise
        summary = str(output).replace("\r", " ").replace("\n", " ")
        summary = summary[:900] + ("..." if len(summary) > 900 else "")
        events_emit("tool_response", f"{method} respondeu em {time.perf_counter() - started:.2f}s · {summary}")
        return output

    data_interface.route_to_vendor = route_with_events
    from tradingagents.agents.utils import (
        core_stock_tools, fundamental_data_tools, macro_data_tools,
        news_data_tools, prediction_markets_tools, technical_indicators_tools,
    )
    patched = []
    for tool_module in (core_stock_tools, fundamental_data_tools, macro_data_tools, news_data_tools, prediction_markets_tools, technical_indicators_tools):
        tool_module.route_to_vendor = route_with_events
        patched.append(tool_module.__name__.rsplit(".", 1)[-1])
    events_emit("instrumentation", f"route_to_vendor instrumentado em: {', '.join(patched)}")

    # The Sentiment Analyst calls fetch_reddit_posts/fetch_stocktwits_messages
    # as plain functions, not through route_to_vendor (they're pre-fetched
    # into its prompt, not tool-called) — so unlike every other data source,
    # these two are otherwise invisible in the log, leaving no way to tell
    # whether they actually returned data or came back blocked.
    from tradingagents.agents.analysts import sentiment_analyst

    def _wrap_sentiment_source(label: str, original_fn):
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            events_emit("sentiment_request", f"Sentimento: buscando {label}...")
            output = original_fn(*args, **kwargs)
            summary = str(output).replace("\r", " ").replace("\n", " ")
            summary = summary[:900] + ("..." if len(summary) > 900 else "")
            events_emit("sentiment_response", f"{label} respondeu em {time.perf_counter() - started:.2f}s · {summary}")
            return output
        return wrapped

    sentiment_analyst.fetch_reddit_posts = _wrap_sentiment_source("Reddit", sentiment_analyst.fetch_reddit_posts)
    sentiment_analyst.fetch_stocktwits_messages = _wrap_sentiment_source("StockTwits", sentiment_analyst.fetch_stocktwits_messages)


def _start_ollama_monitor(ollama_base_url: str, events_emit, stop_event: threading.Event) -> threading.Thread:
    import httpx

    def monitor():
        last_status = None
        last_heartbeat = time.monotonic()
        # Many agent steps (debates, the trader's final call) are one long
        # LLM completion with no tool call in between — nothing else in this
        # process emits an event for minutes at a time, which looks exactly
        # like a hang even though the GPU is genuinely busy (confirmed live:
        # nvidia-smi at 77% during a "silent" stretch). A periodic heartbeat
        # while a model is loaded gives proof of life without the noise of
        # reporting on every 3s poll.
        _HEARTBEAT_SECONDS = 30
        while not stop_event.wait(3):
            try:
                with httpx.Client(timeout=2) as client:
                    running = client.get(f"{ollama_base_url.rstrip('/')}/api/ps").json().get("models", [])
                if running:
                    model_info = running[0]
                    status = (model_info.get("name"), model_info.get("size_vram"), model_info.get("size"))
                    now = time.monotonic()
                    if status != last_status:
                        vram_gb = round((model_info.get("size_vram") or 0) / 1024 / 1024 / 1024, 2)
                        events_emit("ollama", f"Ollama ativo: {model_info.get('name')} · VRAM {vram_gb} GB")
                        last_status = status
                        last_heartbeat = now
                    elif now - last_heartbeat >= _HEARTBEAT_SECONDS:
                        vram_gb = round((model_info.get("size_vram") or 0) / 1024 / 1024 / 1024, 2)
                        events_emit("heartbeat", f"Ainda processando com {model_info.get('name')} · VRAM {vram_gb} GB — sem chamada de ferramenta neste trecho (raciocínio/debate interno do agente).")
                        last_heartbeat = now
                elif last_status != "idle":
                    events_emit("wait", "Ollama sem modelo ativo; aguardando ferramenta/dados de mercado")
                    last_status = "idle"
            except Exception as exc:
                status = f"error:{exc}"
                if status != last_status:
                    events_emit("monitor", f"Monitor Ollama: {exc}")
                    last_status = status

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    return thread


def run_worker(payload: dict[str, Any], queue) -> None:
    """Build the graph and run ``propagate`` fully inside this process.

    ``payload`` keys: symbol (upstream ticker, already normalized), model,
    ollama_base_url, trade_date, results_dir, data_cache_dir, memory_log_path.
    Every field must be picklable (plain str/int/float) since this crosses a
    process boundary on Windows via ``spawn``.
    """
    def emit(kind: str, text: str) -> None:
        _emit(queue, kind, text)

    class _EventLogHandler(logging.Handler):
        """Forward upstream's own warning/error logs (structured-output
        fallbacks, vendor retries, etc.) into the run's event stream.

        These already exist as ``logger.warning(...)`` calls throughout
        ``tradingagents`` (e.g. "structured-output invocation failed;
        retrying once as free text") but only ever reached the terminal —
        a long silent gap in the UI log was, on inspection, actually one of
        these retries plus slow generation, not a hang. Pure logging
        interception: no shared file/connection, so no contention risk like
        the earlier checkpoint-file approach.
        """

        def emit(self, record: logging.LogRecord) -> None:
            try:
                events_emit("warning", f"{record.name}: {record.getMessage()}")
            except Exception:
                pass

    events_emit = emit
    logging.getLogger("tradingagents").addHandler(_EventLogHandler(level=logging.WARNING))

    stop_monitor = threading.Event()
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.agents.utils.rating import is_review
        from langchain_core.callbacks import BaseCallbackHandler

        _install_monkeypatches(emit, payload["trade_date"])

        config = DEFAULT_CONFIG.copy()
        config.update({
            "llm_provider": "ollama",
            "deep_think_llm": payload["model"],
            "quick_think_llm": payload["model"],
            "backend_url": f"{payload['ollama_base_url'].rstrip('/')}/v1",
            "project_dir": payload["project_dir"],
            "data_cache_dir": payload["data_cache_dir"],
            "results_dir": payload["results_dir"],
            "memory_log_path": payload["memory_log_path"],
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "llm_max_retries": 0,
            "news_article_limit": 5,
            "global_news_article_limit": 3,
            "output_language": "Portuguese",
            # Upstream already ships resumable checkpointing (a per-ticker
            # SqliteSaver under data_cache_dir/checkpoints/, keyed by
            # ticker+date+graph-shape) — it just wasn't turned on. A timeout
            # kills this process mid-run, but the checkpoint DB is a real
            # file on disk that survives that; the next attempt for the same
            # ticker+date resumes from the last completed node instead of
            # redoing the whole 15-25min pipeline from scratch. A run that
            # finishes normally (including INCONCLUSIVE) clears its own
            # checkpoint, so this never resumes stale state into a fresh run.
            "checkpoint_enabled": True,
        })

        class EventHandler(BaseCallbackHandler):
            def on_chain_start(self, serialized, inputs, **kwargs):
                emit("agent_start", (serialized or {}).get("name", "LangGraph chain"))

            def on_tool_start(self, serialized, input_str, **kwargs):
                emit("tool", (serialized or {}).get("name", "market tool"))

            def on_chain_end(self, outputs, **kwargs):
                emit("agent_end", "step finished")
                # NOTE: this used to re-open the checkpoint SQLite file here
                # (via checkpoint_step) to report the live step number after
                # every chain completion. That opened a second connection to
                # the same DB file the graph's own long-lived checkpointer
                # connection was already holding open for the whole
                # propagate() call — on_chain_end fires rapidly (every nested
                # chain, not just top-level agent nodes) — and this produced a
                # real, reproducible hang (confirmed live: child process
                # pegged at 0% CPU, every HTTP request to the backend timing
                # out). Ongoing "still working" reassurance is now handled
                # safely by the Ollama heartbeat below (HTTP poll, no file
                # contention) instead of re-reading this file mid-run.

            def on_tool_end(self, output, **kwargs):
                text = str(output).replace("\n", " ")
                emit("tool_end", f"Resposta externa: {text[:700]}{'...' if len(text) > 700 else ''}")

            def on_tool_error(self, error, **kwargs):
                emit("tool_error", f"Ferramenta externa falhou: {error}")

            def on_chain_error(self, error, **kwargs):
                emit("error", str(error))

        emit(
            "config",
            "Analista de sentimento ativado: usa Reddit (funcionando) e StockTwits (às vezes "
            "bloqueado por firewall/anti-robô, degradando sozinho para 'indisponível' sem travar a análise).",
        )
        from tradingagents.graph.checkpointer import checkpoint_step

        graph = TradingAgentsGraph(
            selected_analysts=("market", "social", "news", "fundamentals"),
            debug=True,
            config=config,
            callbacks=[EventHandler()],
        )

        resumed_step = checkpoint_step(
            config["data_cache_dir"], payload["symbol"], str(payload["trade_date"]), graph._run_signature("stock"),
        )
        if resumed_step is not None:
            emit(
                "config",
                f"Checkpoint encontrado (etapa {resumed_step}) de uma tentativa anterior interrompida "
                f"para {payload['symbol']} em {payload['trade_date']} — retomando dali, sem refazer os "
                f"agentes já concluídos.",
            )
        else:
            emit("config", "Nenhum checkpoint anterior para esta data; executando o pipeline do zero.")

        _start_ollama_monitor(payload["ollama_base_url"], emit, stop_monitor)
        emit("run", f"TradingAgentsGraph iniciado para {payload['symbol']} com {payload['model']}")
        emit("graph", "Grafo LangGraph executando os agentes e ferramentas")

        final_state, signal = graph.propagate(payload["symbol"], payload["trade_date"])
        decision_text = str(final_state.get("final_trade_decision", ""))
        emit("complete", f"Decisão final recebida: {signal}")
        queue.put({
            "kind": "result",
            "signal": signal,
            "is_review": is_review(signal),
            "decision_text": decision_text,
        })
    except Exception as exc:
        queue.put({
            "kind": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-4000:],
        })
    finally:
        stop_monitor.set()
        try:
            queue.put({"kind": "__done__"})
        except Exception:
            pass
