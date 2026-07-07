from functools import lru_cache
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_REDIS = "redis://localhost:6379/0"
_DEFAULT_CELERY_BACKEND = "redis://localhost:6379/1"

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
        """Raise if production is misconfigured for hosted deploys."""
        if self.environment != "production":
            return
        if self.is_sqlite:
            raise RuntimeError(
                "FATAL: DATABASE_URL must be set to PostgreSQL in production. "
                "SQLite data is lost on container restart. "
                "Set DATABASE_URL in Railway Variables."
            )
        for name, url in (
            ("CELERY_BROKER_URL", self.celery_broker_url),
            ("CELERY_RESULT_BACKEND", self.celery_result_backend),
        ):
            if "localhost" in url or "127.0.0.1" in url:
                raise RuntimeError(
                    f"FATAL: {name} must point to Redis in production, not localhost. "
                    "Add a Redis service on Railway and reference REDIS_URL."
                )

    # Redis / Celery
    redis_url: str = _DEFAULT_REDIS
    celery_broker_url: str = _DEFAULT_REDIS
    celery_result_backend: str = _DEFAULT_CELERY_BACKEND

    @model_validator(mode="after")
    def wire_celery_from_redis(self) -> Self:
        """When only REDIS_URL is set (e.g. Railway plugin), derive Celery URLs."""
        remote = self.redis_url
        if not remote or "localhost" in remote or "127.0.0.1" in remote:
            return self
        if self.celery_broker_url in (_DEFAULT_REDIS, ""):
            self.celery_broker_url = remote
        if self.celery_result_backend in (_DEFAULT_CELERY_BACKEND, ""):
            base = remote.rsplit("/", 1)[0] if remote.rsplit("/", 1)[-1].isdigit() else remote.rstrip("/")
            self.celery_result_backend = f"{base}/1"
        return self

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