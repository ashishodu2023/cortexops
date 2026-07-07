"""Process entrypoint for API (web) and Celery worker deployments."""
from __future__ import annotations

import os
import sys


def _validate_role_env(role: str) -> None:
    from app.config import get_settings

    settings = get_settings()
    if not settings.is_production:
        return

    settings.validate_production()
    if role == "worker":
        return

    import os as _os

    from app.main import _collect_secret_issues

    errors = _collect_secret_issues(_os.environ)
    if errors:
        raise RuntimeError(f"Missing/insecure secrets: {'; '.join(errors)}")


def _run_web() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


def _run_worker() -> None:
    concurrency = os.environ.get("CELERY_CONCURRENCY", "2")
    os.execvp(
        "celery",
        [
            "celery",
            "-A",
            "app.worker.celery_app.celery",
            "worker",
            "--loglevel=info",
            f"--concurrency={concurrency}",
        ],
    )


def main() -> None:
    role = os.environ.get("SERVICE_ROLE", "web").strip().lower()
    if role in {"web", "api"}:
        _validate_role_env(role)
        _run_web()
    elif role == "worker":
        _validate_role_env(role)
        _run_worker()
    else:
        print(f"Unknown SERVICE_ROLE={role!r} — expected web, api, or worker", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
