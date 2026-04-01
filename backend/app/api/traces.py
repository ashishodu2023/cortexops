
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.auth import get_api_key
from app.services.traces import store_trace, list_traces

router = APIRouter()

class Trace(BaseModel):
    project: str
    prompt: str
    response: str
    latency: float
    error: str | None = None

@router.post("/")
def ingest(trace: Trace, api_key: str = Depends(get_api_key)):
    return store_trace(trace.dict())

@router.get("/")
def get_traces():
    return list_traces()
