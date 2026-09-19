from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    brapi_api_key: str = ""
    alpha_vantage_api_key: str = ""
    twelve_data_api_key: str = ""
    database_url: str = "sqlite:///trading.db"
    trading_mode: str = "PAPER"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    def validate_paper_only(self) -> None:
        if self.trading_mode.upper() != "PAPER":
            raise RuntimeError("Only PAPER trading mode is enabled in this version")


settings = Settings()
settings.validate_paper_only()
