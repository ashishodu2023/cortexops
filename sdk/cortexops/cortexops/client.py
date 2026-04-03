from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from .models import EvalSummary, Trace


class CortexClient:
    """HTTP client for the CortexOps backend API.

    Used by the SDK to push traces and pull eval history.
    Not required for local-only usage.

    Usage:
        client = CortexClient(api_key="cxo-...", base_url="https://api.cortexops.ai")
        client.push_trace(tracer.last_trace())
        history = client.list_runs(project="payments-agent", limit=10)
    """

    DEFAULT_BASE_URL = "https://api.cortexops.ai"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        import httpx
        r = httpx.get(
            urljoin(self.base_url + "/", path.lstrip("/")),
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> dict:
        import httpx
        r = httpx.post(
            urljoin(self.base_url + "/", path.lstrip("/")),
            headers=self._headers(),
            json=data,
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def push_trace(self, trace: Trace) -> dict:
        return self._post("/v1/traces", trace.model_dump(mode="json"))

    def get_trace(self, trace_id: str) -> dict:
        return self._get(f"/v1/traces/{trace_id}")

    def list_traces(self, project: str, limit: int = 50) -> list[dict]:
        return self._get("/v1/traces", {"project": project, "limit": limit})

    def push_eval(self, summary: EvalSummary) -> dict:
        return self._post("/v1/evals", summary.model_dump(mode="json"))

    def list_runs(self, project: str, limit: int = 10) -> list[dict]:
        return self._get("/v1/evals", {"project": project, "limit": limit})

    def run_eval(self, dataset: str, project: str) -> dict:
        """Trigger a server-side eval run (async via Celery)."""
        return self._post("/v1/evals/run", {"dataset": dataset, "project": project})

    def get_eval(self, run_id: str) -> dict:
        return self._get(f"/v1/evals/{run_id}")

    def diff(self, run_id_a: str, run_id_b: str) -> dict:
        return self._get("/v1/evals/diff", {"a": run_id_a, "b": run_id_b})
