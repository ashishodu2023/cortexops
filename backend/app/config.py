from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CORS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://getcortexops.com",
    "https://www.getcortexops.com",
    "https://app.getcortexops.com",
    "https://docs.getcortexops.com",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CortexOps API"
    environment: str = "development"
    debug: bool = False
    version: str = "0.1.0"

    # Database — MUST be set to PostgreSQL in production
    database_url: str = "sqlite+aiosqlite:///./cortexops.db"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    def validate_production(self) -> None:
        """Raise if running SQLite in production."""
        if self.environment == "production" and self.is_sqlite:
            raise RuntimeError(
                "FATAL: DATABASE_URL must be set to PostgreSQL in production. "
                "SQLite data is lost on container restart. "
                "Set DATABASE_URL in Railway Variables."
            )

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Auth
    api_key_header: str = "X-API-Key"
    internal_api_key: str = "dev_internal_key"

    # Eval
    max_eval_cases_per_run: int = 500
    eval_timeout_seconds: int = 300

    # CORS — override with comma-separated CORS_ORIGINS env var
    cors_origins: list[str] = _DEFAULT_CORS

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            parsed = [origin.strip() for origin in value.split(",") if origin.strip()]
            return parsed or _DEFAULT_CORS
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()