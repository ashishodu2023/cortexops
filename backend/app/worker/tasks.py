
from app.worker.celery_app import celery
from app.services.metrics import log_metric
import time, random

@celery.task
def run_eval_task(dataset, project):
    start = time.time()
    success_rate = round(random.uniform(0.85, 0.97), 3)
    latency = round(random.uniform(120, 350), 2)
    log_metric(project, "success_rate", success_rate)
    log_metric(project, "latency", latency)
    return {"project": project, "success_rate": success_rate, "latency": latency}
