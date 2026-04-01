
from datetime import datetime
try:
    from clickhouse_connect import get_client
    client = get_client(host="clickhouse")
except Exception:
    client = None

_memory_metrics = []

def log_metric(project, metric, value):
    row = {"timestamp": datetime.utcnow().isoformat(), "project": project, "metric": metric, "value": value}
    if client:
        try:
            client.insert("metrics", [[datetime.utcnow(), project, metric, float(value)]])
        except Exception:
            _memory_metrics.append(row)
    else:
        _memory_metrics.append(row)

def get_metrics(project: str = None):
    if client:
        try:
            q = "SELECT metric, avg(value) as value FROM metrics GROUP BY metric"
            res = client.query(q)
            return [{"metric": r[0], "value": r[1]} for r in res.result_rows]
        except Exception:
            pass
    # fallback
    agg = {}
    for r in _memory_metrics:
        if project and r["project"] != project:
            continue
        agg.setdefault(r["metric"], []).append(r["value"])
    return [{"metric": k, "value": round(sum(v)/len(v), 3)} for k,v in agg.items()]
