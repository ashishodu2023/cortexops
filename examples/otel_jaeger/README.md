# Export CortexOps traces to Jaeger

This example sends CortexOps traces to [Jaeger](https://www.jaegertracing.io/) over OTLP/HTTP using
`cortexops.otel.OTelExporter`. The same exporter works with any OTLP backend: Grafana Tempo,
Honeycomb, Datadog, New Relic, an OpenTelemetry Collector, or CortexOps' own OTLP endpoint.

## Run it

```bash
cd examples/otel_jaeger
docker compose up -d                    # Jaeger UI on http://localhost:16686
pip install -r requirements.txt         # cortexops[otel]
python run.py
```

Expected output:

```
order 4821: completed http://localhost:16686/trace/3f6c...
order 9999: agent failed (refund policy service timeout)
order 9999: failed    http://localhost:16686/trace/a81e...
```

Open a link to see the waterfall. Each trace looks like this:

```
invoke_agent payments-agent          gen_ai.operation.name=invoke_agent, cortexops.prompt.version=v3
  classify                           gen_ai.operation.name=chat, gen_ai.input/output.messages
  check_order
    execute_tool lookup_order        gen_ai.tool.name, gen_ai.tool.call.arguments/result
  decide
```

The Jaeger trace id is the CortexOps trace id with the dashes removed. You can paste either one
into Jaeger's search box, or jump straight from a CortexOps trace to Jaeger.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `OTelExporter(endpoint=...)` | `OTEL_EXPORTER_OTLP_*` env vars, else `http://localhost:4318` | Base URL or the full `.../v1/traces` URL |
| `headers=` | none | For example `{"x-honeycomb-team": "..."}` |
| `service_name=` | the trace's project | Sets the `service.name` resource attribute |
| `include_content=False` | `True` | Drops prompts, responses, inputs, outputs and tool payloads |
| `span_exporter=` | OTLP/HTTP | Any OTel `SpanExporter`, such as the gRPC exporter |
| `batch=False` | `True` | Export synchronously, which is handy in short scripts and tests |

Call `exporter.shutdown()` (or `force_flush()`) before a short-lived process exits so the batch
processor can flush.

## Clean up

```bash
docker compose down
```

See [docs/opentelemetry.md](../../docs/opentelemetry.md) for the full attribute mapping.
