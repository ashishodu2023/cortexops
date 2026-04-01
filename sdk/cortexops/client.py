
import requests

class CortexClient:
    def __init__(self, api_key, base_url="http://localhost:8000"):
        self.api_key = api_key
        self.base_url = base_url

    def run_eval(self, dataset, project):
        r = requests.post(
            f"{self.base_url}/eval/run",
            json={"dataset": dataset, "project": project},
            headers={"x-api-key": self.api_key}
        )
        return r.json()

    def send_trace(self, project, prompt, response, latency, error=None):
        r = requests.post(
            f"{self.base_url}/traces",
            json={
                "project": project,
                "prompt": prompt,
                "response": response,
                "latency": latency,
                "error": error
            },
            headers={"x-api-key": self.api_key}
        )
        return r.json()
