"""Application settings, loaded from environment variables and `backend/.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # CI passes unset repository variables as empty strings; treat them as "use the default".
        env_ignore_empty=True,
    )

    # Database
    database_url: str = ""
    test_database_url: str = ""

    @field_validator("database_url", "test_database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Accept the URL however it was copied from Neon and select the psycopg v3 driver.

        Handles surrounding whitespace and quotes, Neon's `psql '...'` snippet, and a pasted
        `DATABASE_URL=` prefix.
        """
        url = url.strip()
        if url.startswith("psql "):
            url = url[len("psql ") :].strip()
        if "=" in url.split("://", 1)[0]:
            url = url.split("=", 1)[1].strip()
        url = url.strip("'\"").strip()
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    # LLM
    analyzer_provider: str = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    # Only for reasoning models (e.g. "none" or "low"); leave empty for other models.
    openai_reasoning_effort: str = ""
    llm_max_output_tokens: int = Field(default=400, gt=0)
    openai_price_input_per_1m: float = Field(default=0.0, ge=0)
    openai_price_output_per_1m: float = Field(default=0.0, ge=0)

    # Pipeline limits
    max_news_per_ticker: int = Field(default=8, gt=0)
    news_lookback_hours: int = Field(default=48, gt=0)
    max_tickers_per_run: int = Field(default=30, gt=0)
    watchlist_path: Path = BACKEND_DIR / "watchlist.yaml"

    # API
    cors_origins: str = "http://localhost:5173"

    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.openai_price_input_per_1m
            + output_tokens * self.openai_price_output_per_1m
        ) / 1_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def check_database_url(url: str) -> None:
    """Fail with a readable message. Never includes the URL itself, which holds a password."""
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy backend/.env.example to backend/.env.")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            "DATABASE_URL does not look like a Postgres URL "
            f"(length {len(url)}, contains '://': {'://' in url}). It should start with "
            "postgresql:// - paste only the connection string from Neon, nothing else."
        )
