from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # OpenAI-compatible gateway. Any endpoint that speaks the Chat Completions API works.
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"
    # Leave empty to omit temperature (some reasoning models reject it).
    openai_temperature: str = "0.1"
    # JSON object of extra headers forwarded to the gateway, e.g. {"x-team": "bi"}.
    openai_default_headers: str = ""
    openai_timeout_seconds: float = 120.0

    # Application state (dashboards, metadata, history).
    app_db_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"

    # Demo business database, created on first start.
    demo_enabled: bool = True
    demo_db_path: str = str(BACKEND_DIR / "data" / "demo_sales.db")

    # Execution bounds.
    default_row_limit: int = 500
    max_row_limit: int = 5000
    query_timeout_seconds: float = 15.0
    result_cache_ttl_seconds: int = 120

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"

    @property
    def temperature(self) -> float | None:
        value = self.openai_temperature.strip()
        return float(value) if value else None

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
