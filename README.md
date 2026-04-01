
# CortexOps
**Datadog for AI Agents**

CortexOps is an evaluation and observability platform for AI agents:
- Evaluate agents (golden datasets)
- Trace debugging (prompt/response/tool calls)
- Real-time monitoring & alerts
- AI-assisted root cause analysis

## Quickstart

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Worker (async eval)
```bash
cd backend
celery -A app.worker.celery_app.celery worker --loglevel=info
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### SDK (example)
```python
from cortexops.client import CortexClient

client = CortexClient(api_key="cx_test_key")
print(client.run_eval(dataset="golden_v1", project="demo"))
```

Open:
- API: http://localhost:8000
- UI: http://localhost:3000
