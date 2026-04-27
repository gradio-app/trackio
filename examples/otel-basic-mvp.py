"""Minimal OpenTelemetry -> Trackio example.

Run a writable Trackio dashboard first:

    trackio show

Then set the write token printed by Trackio and run this example:

    export TRACKIO_WRITE_TOKEN=<write-token>
    python examples/otel-basic-mvp.py

The span appears in the Trackio dashboard's Traces tab.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def main() -> None:
    endpoint = os.getenv(
        "TRACKIO_OTEL_ENDPOINT",
        "http://localhost:7860/otel/v1/traces",
    )
    write_token = os.getenv("TRACKIO_WRITE_TOKEN")
    headers = {"x-trackio-write-token": write_token} if write_token else {}

    provider = TracerProvider(
        resource=Resource(
            {
                "trackio.project": os.getenv("TRACKIO_PROJECT", "otel-basic-mvp"),
                "trackio.run": os.getenv("TRACKIO_RUN", "manual-span"),
                "service.name": "trackio-otel-basic-example",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("trackio.examples.otel-basic-mvp")
    with tracer.start_as_current_span("manual llm call") as span:
        span.set_attribute("openinference.span.kind", "llm")
        span.set_attribute("input.value", "Say hello to Trackio.")
        span.set_attribute("output.value", "Hello from OpenTelemetry.")
        span.set_attribute("llm.model_name", "example-model")
        span.set_attribute("llm.token_count.prompt", 5)
        span.set_attribute("llm.token_count.completion", 4)

    provider.force_flush()
    provider.shutdown()
    print(f"Sent one OTLP span to {endpoint}")


if __name__ == "__main__":
    main()
