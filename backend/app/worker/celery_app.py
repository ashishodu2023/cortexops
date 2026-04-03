from celery import Celery

from ..config import get_settings

settings = get_settings()

celery = Celery(
    "cortexops",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=settings.eval_timeout_seconds,
    task_time_limit=settings.eval_timeout_seconds + 30,
    worker_prefetch_multiplier=1,
)
