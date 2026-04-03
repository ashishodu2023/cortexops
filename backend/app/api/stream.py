
from fastapi import APIRouter, WebSocket

router = APIRouter()

connections = []

@router.websocket("/ws/traces")
async def ws_traces(ws: WebSocket):
    await ws.accept()
    connections.append(ws)
    try:
        while True:
            await ws.receive_text()
    except Exception:
        connections.remove(ws)
