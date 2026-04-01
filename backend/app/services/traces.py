
from datetime import datetime
try:
    from clickhouse_connect import get_client
    client = get_client(host="clickhouse")
except Exception:
    client = None

_memory_traces = []

def store_trace(data):
    row = {
        "timestamp": datetime.utcnow().isoformat(),
        "project": data.get("project"),
        "prompt": data.get("prompt"),
        "response": data.get("response"),
        "latency": float(data.get("latency", 0)),
        "error": data.get("error", "")
    }
    if client:
        try:
            client.insert("traces", [[
                datetime.utcnow(),
                row["project"],
                row["prompt"],
                row["response"],
                row["latency"],
                row["error"]
            ]])
        except Exception:
            _memory_traces.append(row)
    else:
        _memory_traces.append(row)
    return row

def list_traces(limit: int = 50):
    if client:
        try:
            q = "SELECT project, prompt, response, latency, error FROM traces ORDER BY timestamp DESC LIMIT 50"
            res = client.query(q)
            return [
                {"project": r[0], "prompt": r[1], "response": r[2], "latency": r[3], "error": r[4]}
                for r in res.result_rows
            ]
        except Exception:
            pass
    return list(reversed(_memory_traces[-limit:]))
