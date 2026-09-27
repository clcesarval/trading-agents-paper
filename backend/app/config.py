from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    brapi_api_key: str = ""
    alpha_vantage_api_key: str = ""
    twelve_data_api_key: str = ""
    database_url: str = "sqlite:///data/trading.db"
    trading_mode: str = "PAPER"
    # 900s was sized for the 8-agent pipeline alone; the Sentiment Analyst
    # (Reddit + StockTwits) adds real pre-fetch latency on top of that —
    # observed up to ~2 extra minutes when Reddit rate-limits and backs off —
    # which was enough to push some runs past the old timeout (#1 reported
    # live: a redo hit exactly 900s after the Reddit fetch alone took 119s).
    analysis_timeout_seconds: int = 1500
    # "" = leave the model's own default. "none" turns off the "thinking" phase of
    # models like Qwen3 (sent as reasoning_effort on every chat request).
    llm_reasoning_effort: str = ""
    # Ollama's default sampling temperature (~0.8) is a real, measured source of
    # the same-date-different-decision instability (research on the TradingAgents
    # framework found ~9% return std just from varying temperature/seed/top_p).
    # Lower reduces (does not eliminate — the model's own "thinking" tokens are
    # still sampled) how often two runs of the same date diverge. "" leaves the
    # model's own default, matching behavior before this setting existed.
    llm_temperature: float | str = 0.2
    # Indicators are computed by code and handed to the market analyst instead of hoping
    # the model calls the tools. Set GROUNDED_MARKET_ANALYST=false to get the old behaviour.
    grounded_market_analyst: bool = True
    # A Portfolio Manager decision whose Rating contradicts its own Executive
    # Summary (e.g. "Rating: Hold" next to "Posicione-se comprando...") gets one
    # automatic revision attempt instead of reaching the trader as-is (#seen live
    # PETR4 2026-08-17: all 3 consensus attempts had this exact contradiction).
    consistent_portfolio_manager: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    def validate_paper_only(self) -> None:
        if self.trading_mode.upper() != "PAPER":
            raise RuntimeError("Only PAPER trading mode is enabled in this version")


settings = Settings()
settings.validate_paper_only()
