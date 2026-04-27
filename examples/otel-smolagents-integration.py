"""smolagents + OpenInference + OpenTelemetry -> Trackio example.

Run a writable Trackio dashboard first:

    trackio show

Then set the write token printed by Trackio and run this example:

    pip install smolagents openinference-instrumentation-smolagents \
        opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
    export TRACKIO_WRITE_TOKEN=<write-token>
    python examples/otel-smolagents-integration.py

This example uses a local dummy smolagents model, so it does not require an LLM
API key. The agent run appears in the Trackio dashboard's Traces tab.

Note: smolagents currently declares a narrower huggingface-hub dependency than
Trackio. If installing smolagents downgrades huggingface-hub in a Trackio dev
environment, reinstall Trackio's supported range with:

    pip install "huggingface-hub>=1.10.0,<2"
"""

import os

from openinference.instrumentation.smolagents import SmolagentsInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from smolagents import CodeAgent, Model
from smolagents.models import ChatMessage, MessageRole


class DemoModel(Model):
    def generate(self, messages, **kwargs):
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="```python\nfinal_answer('Trackio received this smolagents trace')\n```",
        )


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
                "trackio.project": os.getenv("TRACKIO_PROJECT", "otel-smolagents"),
                "trackio.run": os.getenv("TRACKIO_RUN", "dummy-agent"),
                "service.name": "smolagents",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
    )

    SmolagentsInstrumentor().instrument(tracer_provider=provider)

    agent = CodeAgent(
        tools=[],
        model=DemoModel(model_id="trackio-demo-model"),
        max_steps=1,
    )
    result = agent.run("Return a short confirmation that Trackio tracing works.")

    provider.force_flush()
    provider.shutdown()
    print(f"Agent result: {result}")
    print(f"Sent smolagents OpenInference spans to {endpoint}")


if __name__ == "__main__":
    main()
