from __future__ import annotations

from urllib.parse import urljoin

from .models import Trace


class CortexClient:
    """HTTP client for the CortexOps backend API.

    Used by the SDK to push traces and pull eval history.
    Not required for local-only usage.

    Usage:
        client = CortexClient(api_key="cxo-...", base_url="https://api.cortexops.ai")
        client.push_trace(tracer.last_trace())
        history = client.list_runs(project="payments-agent", limit=10)
    """

    DEFAULT_BASE_URL = "https://api.getcortexops.com"

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
            "X-API-Key": self.api_key,
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

    def push_eval(self, summary, *, dataset: dict | None = None, prompt: dict | None = None) -> dict:
        """Push a completed EvalSuite summary to POST /v1/evals/ingest."""
        if hasattr(summary, "model_dump"):
            data = summary.model_dump(mode="json")
        else:
            data = dict(summary)
        for cr in data.get("case_results", []):
            cr.pop("trace", None)
            if cr.get("failure_kind") and hasattr(cr["failure_kind"], "value"):
                cr["failure_kind"] = cr["failure_kind"].value
        if dataset:
            data["dataset"] = dataset
        if prompt:
            data["prompt"] = prompt
        return self._post("/v1/evals/ingest", data)

    def project_for_key(self) -> str:
        """Return the project bound to the current API key."""
        return self._get("/v1/traces/quota")["project"]

    def list_runs(self, project: str, limit: int = 10) -> list[dict]:
        return self._get("/v1/evals", {"project": project, "limit": limit})

    def run_eval(self, dataset: str, project: str) -> dict:
        """Trigger a server-side eval run (async via Celery)."""
        return self._post("/v1/evals/run", {"dataset": dataset, "project": project})

    def get_eval(self, run_id: str) -> dict:
        return self._get(f"/v1/evals/{run_id}")

    def diff(self, run_id_a: str, run_id_b: str) -> dict:
        return self._get("/v1/evals/diff", {"a": run_id_a, "b": run_id_b})

    def list_datasets(self) -> list[dict]:
        return self._get("/v1/eval/datasets")

    def get_dataset(self, dataset_id: str) -> dict:
        return self._get(f"/v1/eval/datasets/{dataset_id}")

    def create_dataset(self, name: str, cases: list[dict], description: str = "") -> dict:
        return self._post("/v1/eval/datasets", {
            "name": name,
            "description": description,
            "cases": cases,
        })

    def add_case_from_trace(
        self,
        dataset_id: str,
        trace_id: str,
        *,
        case_id: str | None = None,
    ) -> dict:
        """Promote a production trace into a golden dataset case."""
        body: dict = {"trace_id": trace_id}
        if case_id:
            body["case_id"] = case_id
        return self._post(f"/v1/eval/datasets/{dataset_id}/cases/from-trace", body)

    def commit_prompt(
        self,
        project: str,
        prompt_name: str,
        content: str,
        *,
        model: str = "",
        temperature: float = 0.7,
        commit_message: str = "",
        author: str = "",
    ) -> dict:
        return self._post("/v1/prompts", {
            "project": project,
            "prompt_name": prompt_name,
            "content": content,
            "model": model,
            "temperature": temperature,
            "commit_message": commit_message,
            "author": author,
        })

    def list_prompt_catalog(self, project: str) -> list[dict]:
        return self._get("/v1/prompts/catalog", {"project": project})
