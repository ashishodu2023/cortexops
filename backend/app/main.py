
from fastapi import FastAPI
from app.api import eval, traces, metrics, stream

app = FastAPI(title="CortexOps API")

app.include_router(eval.router, prefix="/eval")
app.include_router(traces.router, prefix="/traces")
app.include_router(metrics.router, prefix="/metrics")
app.include_router(stream.router)

@app.get("/")
def root():
    return {"status": "ok"}
