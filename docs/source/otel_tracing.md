# OpenTelemetry Traces

Trackio can receive OpenTelemetry trace data over OTLP/HTTP and show it in the
dashboard's **Traces** tab. This is useful for agent and LLM frameworks that
already emit OpenTelemetry or OpenInference spans, such as smolagents through
`openinference-instrumentation-smolagents`.

This is a minimal v1 receiver:

- supported endpoint: `POST /otel/v1/traces`
- supported encoding: OTLP protobuf (`application/x-protobuf`)
- supported signal: traces
- storage: each incoming span is converted to a `trackio.Trace` log entry

## Start Trackio

Launch a writable Trackio dashboard:

```bash
trackio show
```

Use the write-access URL or token printed by the server. For a local server,
OTLP requests must include the same write token as normal remote logging.

## Configure an OTLP Exporter

Point your OpenTelemetry exporter at Trackio:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="http://localhost:7860/otel/v1/traces"
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="x-trackio-write-token=<write-token>"
```

Set the Trackio project and run using OpenTelemetry resource attributes:

```python
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

provider = TracerProvider(
    resource=Resource(
        {
            "trackio.project": "my-project",
            "trackio.run": "agent-run",
            "service.name": "smolagents",
        }
    )
)
```

If `trackio.project` is not set, Trackio uses the `project` query parameter if
present, then falls back to `otel-traces`. If `trackio.run` is not set, Trackio
uses `service.name`, then falls back to `otel`.

## Example: smolagents with OpenInference

```bash
pip install smolagents opentelemetry-sdk opentelemetry-exporter-otlp-proto-http openinference-instrumentation-smolagents
```

```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from openinference.instrumentation.smolagents import SmolagentsInstrumentor

provider = TracerProvider(
    resource=Resource(
        {
            "trackio.project": "agent-debugging",
            "trackio.run": "smolagents",
            "service.name": "smolagents",
        }
    )
)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
SmolagentsInstrumentor().instrument(tracer_provider=provider)

# Run your smolagents application normally. Spans will appear in Trackio.
```

## Notes

Trackio preserves the raw span attributes in trace metadata and maps common
OpenInference fields such as `input.value`, `output.value`, and indexed
`llm.input_messages.*` / `llm.output_messages.*` attributes into conversational
messages for the Traces tab.

Runnable examples are available in `examples/otel-basic-mvp.py` and
`examples/otel-smolagents-integration.py`.
