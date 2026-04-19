from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # CORS
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://getcortexops.com",
        "https://www.getcortexops.com",
        "https://app.getcortexops.com",
        "https://docs.getcortexops.com",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()