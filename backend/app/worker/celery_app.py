
from celery import Celery

celery = Celery(
    "cortexops",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0"
)
