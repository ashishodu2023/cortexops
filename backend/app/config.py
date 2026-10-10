import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Set by Railway on every deployment, whose edge proxy overwrites any client-supplied X-Forwarded-For.
_RAILWAY_MARKERS = ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID")

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
    version: str = "0.6.0"

    # Database — MUST be set to PostgreSQL in production
    database_url: str = "sqlite+aiosqlite:///./cortexops.db"
    # Apply Alembic migrations on startup (see docs/migrations.md)
    run_migrations: bool = False

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

    # CORS — override with comma-separated CORS_ORIGINS env var (a JSON array also works).
    # The `| str` lets pydantic-settings pass non-JSON env values through to the validator below.
    cors_origins: list[str] | str = _DEFAULT_CORS

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            parsed = [origin.strip() for origin in value.split(",") if origin.strip()]
            return parsed or _DEFAULT_CORS
        return value

    # Peers allowed to set X-Forwarded-For: comma-separated IPs/CIDRs, or "*" for any peer.
    # Unset: any peer on Railway (only its edge reaches the app publicly), otherwise none.
    trusted_proxies: str | None = None

    @property
    def effective_trusted_proxies(self) -> str:
        if self.trusted_proxies is not None:
            return self.trusted_proxies
        return "*" if any(os.environ.get(name) for name in _RAILWAY_MARKERS) else ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()