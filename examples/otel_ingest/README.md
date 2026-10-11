# Send OpenTelemetry traces to CortexOps

If your app is already instrumented with OpenTelemetry, for example with
[OpenLLMetry](https://github.com/traceloop/openllmetry), [OpenInference](https://github.com/Arize-ai/openinference),
Pydantic Logfire, or any library that follows the
[GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), you can send traces to
CortexOps without the CortexOps SDK. Point the OTLP exporter at CortexOps:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.getcortexops.com/v1/otlp
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer cxo-..."
```

## Run the example

`app.py` is a small OpenAI tool-calling agent. Pick OpenLLMetry or OpenInference to instrument it:

```bash
cd examples/otel_ingest
pip install -r requirements.txt
export CORTEXOPS_API_KEY=cxo-...                         # used as the Bearer token
python app.py --instrumentation openllmetry              # or: --instrumentation openinference
```

If `OPENAI_API_KEY` is not set (or you pass `--mock`), the OpenAI API is replaced with a canned local
response. The instrumentation still records real spans, so the example runs without an OpenAI account.

```
agent answer: Order 4821 was delivered, so the refund is approved.
exported to https://api.getcortexops.com/v1/otlp; CortexOps trace id 186560f1-b103-4be7-dcbc-591265e80dbb
```

Then look at the trace in the dashboard, or fetch it from the API:

```bash
curl -H "X-API-Key: $CORTEXOPS_API_KEY" https://api.getcortexops.com/v1/traces/<trace id>
```

The stored trace has:

- **Trace:** input and output from the `invoke_agent` root span, prompt `refund-system` / `v3`, and the
  environment from `deployment.environment.name`.
- **Nodes:** two LLM nodes (`openai.chat` or `ChatCompletion`) with model, provider, token usage, and
  the rendered prompt and response.
- **Tool calls:** `lookup_order`, with arguments, result and `call_id`.

## Against a local backend

```bash
cd backend && ENVIRONMENT=development uvicorn app.main:app --port 8000
curl -X POST localhost:8000/v1/keys/bootstrap -H 'Content-Type: application/json' -d '{"project":"otel-demo"}'
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000/v1/otlp OTEL_SERVICE_NAME=otel-demo \
  CORTEXOPS_API_KEY=<raw_key from bootstrap> python examples/otel_ingest/app.py
```

## Other setups

**Traceloop SDK.** Pass CortexOps as the endpoint:

```python
from traceloop.sdk import Traceloop
Traceloop.init(app_name="refund-service", api_endpoint="https://api.getcortexops.com/v1/otlp",
               headers={"Authorization": "Bearer cxo-..."})
```

**Pydantic Logfire.** With the same `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS`
environment variables set, configure Logfire not to send to its own backend:

```python
import logfire
logfire.configure(send_to_logfire=False, service_name="refund-service")
logfire.instrument_openai()
```

**OpenTelemetry Collector.** Fan out to CortexOps alongside your other backends:

```yaml
exporters:
  otlphttp/cortexops:
    endpoint: https://api.getcortexops.com/v1/otlp
    headers:
      Authorization: Bearer ${env:CORTEXOPS_API_KEY}
service:
  pipelines:
    traces:
      exporters: [otlphttp/cortexops]
```

**Routing to a project.** Traces go to the API key's project. Set the resource attribute
`cortexops.project` to choose a project explicitly; the key must have access to it.

See [docs/opentelemetry.md](../../docs/opentelemetry.md) for the full attribute mapping and limits.
