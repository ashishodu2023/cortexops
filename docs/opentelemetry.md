# OpenTelemetry

CortexOps works with OpenTelemetry in both directions:

- **Ingest.** Apps instrumented with OpenTelemetry can send traces to CortexOps over OTLP/HTTP
  without the CortexOps SDK. This covers OpenLLMetry/Traceloop, Arize OpenInference, Pydantic
  Logfire, and anything that follows the GenAI semantic conventions.
- **Export.** CortexOps SDK users can export their traces to any OTel backend, such as Jaeger,
  Grafana Tempo, Honeycomb, Datadog or an OpenTelemetry Collector.

In both directions the OTel trace id and the CortexOps trace id are the same 128-bit value.
CortexOps formats it as a UUID; OTel formats it as 32 hex characters.

## Ingest: OTLP/HTTP endpoint

| | |
|---|---|
| Endpoint base | `https://api.getcortexops.com/v1/otlp` |
| Traces URL | `POST https://api.getcortexops.com/v1/otlp/v1/traces` |
| Encodings | `application/x-protobuf` (default for OTLP/HTTP exporters) and `application/json` (OTLP JSON) |
| Compression | `Content-Encoding: gzip` or none |
| Auth | `Authorization: Bearer cxo-...` or `X-API-Key: cxo-...` |

OTLP exporters append `/v1/traces` to the base endpoint, so the standard environment variables are
all you need:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.getcortexops.com/v1/otlp
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer cxo-..."
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf   # gRPC is not supported
```

If you configure traces separately, note that the signal-specific variable takes the **full** URL:
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://api.getcortexops.com/v1/otlp/v1/traces` (with
`OTEL_EXPORTER_OTLP_TRACES_HEADERS` for the key).

Quick test with curl and OTLP JSON:

```bash
curl -X POST https://api.getcortexops.com/v1/otlp/v1/traces \
  -H "Authorization: Bearer $CORTEXOPS_API_KEY" -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"refund-service"}}]},
       "scopeSpans":[{"spans":[{"traceId":"5b8efff798038103d269b633813fc60c","spanId":"eee19b7ec3c1b174",
       "name":"invoke_agent refund-agent","kind":1,"startTimeUnixNano":"1760000000000000000",
       "endTimeUnixNano":"1760000001200000000","attributes":[{"key":"gen_ai.operation.name",
       "value":{"stringValue":"invoke_agent"}}]}]}]}]}'
# -> {}    (stored as trace 5b8efff7-9803-8103-d269-b633813fc60c)
```

Runnable example with OpenLLMetry and OpenInference: [examples/otel_ingest](../examples/otel_ingest/).

### Auth, limits and responses

Ingest follows the same rules as `POST /v1/traces`:

- The key needs `read_write` scope. A `read_only` key gets `403`.
- **Quota.** Each new OTel trace counts as one trace against the monthly quota (5,000 on the free
  tier). Spans that merge into a trace already stored do not count again.
- **Size.** Each CortexOps trace is limited to 128KB after mapping, and the whole request body to
  8MB after decompression.
- **Redaction.** PII redaction (emails, card numbers, SSNs, phone numbers, API keys and bearer tokens)
  runs before storage, exactly as for SDK traces. Span ids are kept.

Responses follow the OTLP/HTTP spec:

| Situation | Response |
|---|---|
| All spans stored | `200`, empty `ExportTraceServiceResponse` (`{}` in JSON) |
| Some traces rejected (quota, size, project access, malformed ids) | `200` with `partialSuccess.rejectedSpans` and `errorMessage` |
| Every trace rejected | The rejection status (`429`, `403`, `413` or `400`) with a `google.rpc.Status` body |
| Missing or invalid key | `401` |
| Unsupported `Content-Type` / `Content-Encoding` | `415` |
| Concurrent write to the same new trace | `503`. OTLP exporters retry automatically. |

Success and `Status` bodies use the request's encoding: protobuf in, protobuf out.

### Project, environment and prompt version

| CortexOps field | Source |
|---|---|
| project | Resource `cortexops.project` if set (the key must have access, otherwise the trace is rejected with `403`). Otherwise `service.name` if the key may write to that project. Otherwise the API key's project. |
| environment | Resource `deployment.environment.name` or `deployment.environment`, else the root span's same attributes, else `development` |
| prompt_name / prompt_version | `cortexops.prompt.name` / `cortexops.prompt.version` on the root span, the resource, or any span |
| case_id | Root span `cortexops.case_id` |

`service.name` is only a hint. OTel SDKs always set it, using `unknown_service:<lang>` by default,
so a `service.name` that doesn't match a project you can access falls back to the key's project. It
is still recorded in `metadata.otel.service_name`.

### Trace structure

Each OTel trace becomes **one** CortexOps trace. The record id is the OTel trace id formatted as a
UUID, so `GET /v1/traces/<uuid>` finds it.

- **Root span** (no parent): provides the trace's input, output, latency and status. A root span that
  is itself an LLM call also appears as a node.
- **Child spans:** become `nodes`, ordered by start time, with `latency_ms` taken from the start and
  end time.
- **Tool spans:** become `tool_calls` on the nearest ancestor node. Tools that run directly under the
  root (the usual agent loop) attach to a node named after the root span, marked `"synthetic": true`.
- **Errors:** a span with status `ERROR` or an `exception` event marks the trace `failed`. The
  `failure_detail` comes from the root's error if it has one, otherwise from the first failing span
  (`"<span>: <exception.type>: <exception.message>"`). The `failure_kind` is `timeout` when the
  message mentions a timeout, otherwise `unknown`.
- **Batches:** a `BatchSpanProcessor` exports finished spans every few seconds, so a long agent run
  arrives across several requests, usually children first and the root last. Later spans merge into
  the stored trace, and spans are deduplicated by span id, so exporter retries are safe.
- **Names:** node names are span names. For Pydantic Logfire, whose span names are message
  templates, the rendered `logfire.msg` is used instead.

Ingested traces are regular CortexOps traces. They appear in the dashboard and in `GET /v1/traces`
(filterable by `status`, `environment`, `prompt_name` and `prompt_version`), and they can be
promoted into golden datasets (`POST /v1/eval/datasets/{id}/cases/from-trace`). The case input is the
root span's input and the expected tools are the ingested tool calls.

A span's category comes from the first of these that matches:

| Category | GenAI semconv | OpenInference | Traceloop |
|---|---|---|---|
| tool | `gen_ai.operation.name=execute_tool` | `openinference.span.kind=TOOL` | `traceloop.span.kind=tool` |
| llm | `gen_ai.operation.name` in `chat`, `text_completion`, `generate_content`, `embeddings` | `LLM`, `EMBEDDING` | `llm.request.type` set |
| agent | `invoke_agent`, `create_agent` | `AGENT` | `agent` |
| chain | | `CHAIN` | `workflow`, `task` |
| retriever / guardrail / evaluator | | `RETRIEVER`, `RERANKER`, `GUARDRAIL`, `EVALUATOR` | |

Fallbacks: a span with `gen_ai.tool.name` is treated as a tool, and a span with a model attribute
is treated as an LLM span.

### Attribute mapping

| CortexOps node / tool field | Attributes, in priority order |
|---|---|
| `model` | `gen_ai.response.model`, `gen_ai.request.model`, `llm.model_name`, `llm.request.model` |
| `provider` | `gen_ai.provider.name`, `gen_ai.system`, `llm.provider`, `llm.system` |
| `operation` | `gen_ai.operation.name` |
| `usage.input_tokens` | `gen_ai.usage.input_tokens`, `gen_ai.usage.prompt_tokens`, `llm.token_count.prompt` |
| `usage.output_tokens` | `gen_ai.usage.output_tokens`, `gen_ai.usage.completion_tokens`, `llm.token_count.completion` |
| `llm_prompt`, `input.messages` | `gen_ai.input.messages` (JSON), `gen_ai.prompt.N.role/content`, `llm.input_messages.N.message.role/content`, `gen_ai.content.prompt` event (`gen_ai.prompt`), `gen_ai.{system,user,assistant,tool}.message` events, `gen_ai.prompt` attribute |
| `llm_response`, `output.messages` | `gen_ai.output.messages` (JSON), `gen_ai.completion.N.*`, `llm.output_messages.N.message.*` (including indexed `tool_calls`), `gen_ai.content.completion` event (`gen_ai.completion`), `gen_ai.choice` events, `gen_ai.completion` attribute |
| node `input` / `output` | LLM messages above, else `input.value` / `output.value` (OpenInference), else `traceloop.entity.input` / `traceloop.entity.output`. JSON strings are parsed; plain strings become `{"value": ...}`. |
| `entity_name` | `traceloop.entity.name`, `gen_ai.agent.name` |
| tool `name` | `gen_ai.tool.name`, `tool.name`, `traceloop.entity.name`, else the span name |
| tool `args` | `gen_ai.tool.call.arguments`, `input.value`, `traceloop.entity.input` |
| tool `result` | `gen_ai.tool.call.result`, `output.value`, `traceloop.entity.output` |
| tool `call_id` | `gen_ai.tool.call.id` |
| `status` / `error` | span status `ERROR`, `exception` event (`exception.type`, `exception.message`), `error.type` |
| `attributes` | All remaining non-content span attributes (up to 64, values truncated to 1KB; `logfire.json_schema` dropped) |

Trace-level `metadata` contains `source: "otlp"`, summed `usage`, the `models` used, and an `otel`
block with `trace_id`, root span details, `service_name`, instrumentation `scopes` and `span_count`.

### Not supported (yet)

- OTLP/gRPC. Use the HTTP exporters with `http/protobuf` or `http/json`.
- Logs and metrics signals. Only traces are ingested.
- A trace whose spans all have remote parents (no parentless span reaches CortexOps) has no root.
  Its nodes are still stored, but its input and output stay empty and its latency covers only the
  spans received.

## Export: CortexOps traces to any OTel backend

```bash
pip install 'cortexops[otel]'     # opentelemetry-sdk + OTLP/HTTP exporter; not a core dependency
```

```python
from cortexops import CortexTracer
from cortexops.otel import OTelExporter

exporter = OTelExporter(endpoint="http://localhost:4318")          # Jaeger / Collector / Tempo
tracer = CortexTracer(project="payments-agent", exporters=[exporter])

agent = tracer.wrap(my_langgraph_app)
agent.invoke({"messages": [...]})

exporter.shutdown()   # flush before a short-lived process exits
```

Every trace the tracer records, including errors captured while unsampled, is passed to each
exporter in `exporters=[...]`. Exporter failures are logged at debug level and never break the
agent. Any object with an `export(trace)` method works as an exporter.

Runnable example with Jaeger: [examples/otel_jaeger](../examples/otel_jaeger/).

### Span layout

```
invoke_agent <project>             root span, start = trace.timestamp, duration = total_latency_ms
  <node_name>                      one span per node; CLIENT kind + gen_ai.operation.name=chat for LLM nodes
    execute_tool <tool name>       one span per tool call, laid out sequentially inside the node
```

| Span | Attributes |
|---|---|
| Resource | `service.name` (default: project), `cortexops.project`, `deployment.environment.name`, plus `resource_attributes=` |
| Root | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name`, `cortexops.trace_id`, `cortexops.run_id`, `cortexops.status`, `cortexops.case_id`, `cortexops.prompt.name/version`, `cortexops.failure_kind`, `cortexops.metadata.*`, `input.value`, `output.value`. On failure: status `ERROR`, `error.type`, and an `exception` event. |
| Node | `cortexops.node.id`, `cortexops.node.name`, `input.value`, `output.value`; LLM nodes add `gen_ai.input.messages` / `gen_ai.output.messages` |
| Tool | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.type=function`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `cortexops.tool.status`; error/timeout set status `ERROR` and `error.type` |

### Options

| Argument | Default | Purpose |
|---|---|---|
| `endpoint` | `OTEL_EXPORTER_OTLP_*` env vars, else `http://localhost:4318` | OTLP/HTTP base URL or full `/v1/traces` URL |
| `headers` | `OTEL_EXPORTER_OTLP_HEADERS` | For example `{"x-honeycomb-team": "..."}` |
| `service_name` | trace project | `service.name` resource attribute |
| `resource_attributes` | none | Extra resource attributes |
| `span_exporter` | OTLP/HTTP | Any OTel `SpanExporter`, such as gRPC, console or in-memory |
| `batch` | `True` | `False` exports synchronously (scripts, tests) |
| `include_content` | `True` | `False` drops inputs, outputs, prompts, responses and tool arguments/results |
| `timeout` | `10.0` | OTLP export timeout in seconds |

The exporter uses its own `TracerProvider`, so it never replaces or modifies the application's
global OpenTelemetry setup. Spans from your own OTel instrumentation and spans exported from
CortexOps traces can safely go to the same backend.

### Sending SDK traces to CortexOps over OTLP

`OTelExporter` can also target CortexOps' own ingest endpoint. This is useful when traces must go
through an OpenTelemetry Collector:

```python
OTelExporter(endpoint="https://api.getcortexops.com/v1/otlp",
             headers={"Authorization": "Bearer cxo-..."})
```

For direct use, the SDK's built-in hosted mode (`CortexTracer(api_key=...)`) is simpler and
preserves the trace exactly as recorded.
