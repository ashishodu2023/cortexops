
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.worker.tasks import run_eval_task
from app.core.auth import get_api_key

router = APIRouter()

class EvalRequest(BaseModel):
    dataset: str
    project: str

@router.post("/run")
def run_eval(req: EvalRequest, api_key: str = Depends(get_api_key)):
    task = run_eval_task.delay(req.dataset, req.project)
    return {"task_id": task.id}
