from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CortexOps API"
    environment: str = "development"
    debug: bool = False
    version: str = "0.1.0"

    # Database
    database_url: str = "sqlite+aiosqlite:///./cortexops.db"

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
    cors_origins: list[str] = ["http://localhost:3000", "https://cortexops.ai"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
