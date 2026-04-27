import json

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span
from starlette.testclient import TestClient

from trackio.otel import ingest_otlp_trace_bytes
from trackio.server import build_starlette_app_only
from trackio.sqlite_storage import SQLiteStorage


def _kv(key, value):
    any_value = AnyValue()
    if isinstance(value, bool):
        any_value.bool_value = value
    elif isinstance(value, int):
        any_value.int_value = value
    elif isinstance(value, float):
        any_value.double_value = value
    else:
        any_value.string_value = value
    return KeyValue(key=key, value=any_value)


def _request_bytes():
    span = Span(
        trace_id=bytes.fromhex("0" * 31 + "1"),
        span_id=bytes.fromhex("0" * 15 + "2"),
        name="agent run",
        kind=Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=1_700_000_000_000_000_000,
        end_time_unix_nano=1_700_000_001_000_000_000,
        attributes=[
            _kv("input.value", "hello"),
            _kv("output.value", "world"),
            _kv("openinference.span.kind", "agent"),
        ],
    )
    resource_spans = ResourceSpans(
        resource=Resource(
            attributes=[
                _kv("trackio.project", "otel-project"),
                _kv("service.name", "smolagents"),
                _kv("service.instance.id", "service-1"),
            ]
        ),
        scope_spans=[ScopeSpans(spans=[span])],
    )
    return ExportTraceServiceRequest(
        resource_spans=[resource_spans]
    ).SerializeToString()


def _smolagents_request_bytes():
    spans = [
        Span(
            trace_id=bytes.fromhex("0" * 31 + "3"),
            span_id=bytes.fromhex("0" * 15 + "4"),
            name="FinalAnswerTool",
            start_time_unix_nano=1_700_000_000_000_000_000,
            attributes=[
                _kv(
                    "input.value",
                    json.dumps(
                        {
                            "args": ["Trackio received this smolagents trace"],
                            "sanitize_inputs_outputs": False,
                            "kwargs": {},
                        }
                    ),
                ),
                _kv("output.value", "Trackio received this smolagents trace"),
            ],
        ),
        Span(
            trace_id=bytes.fromhex("0" * 31 + "3"),
            span_id=bytes.fromhex("0" * 15 + "5"),
            name="Step 1",
            start_time_unix_nano=1_700_000_001_000_000_000,
            attributes=[
                _kv(
                    "input.value",
                    json.dumps({"memory_step": "ActionStep(...lots of state...)"}),
                ),
                _kv("output.value", "Execution logs: Last output from code snippet"),
            ],
        ),
        Span(
            trace_id=bytes.fromhex("0" * 31 + "3"),
            span_id=bytes.fromhex("0" * 15 + "6"),
            name="CodeAgent.run",
            start_time_unix_nano=1_700_000_002_000_000_000,
            attributes=[
                _kv(
                    "input.value",
                    json.dumps(
                        {
                            "task": "Return a short confirmation that Trackio tracing works.",
                            "stream": False,
                        }
                    ),
                ),
                _kv("output.value", "Trackio received this smolagents trace"),
            ],
        ),
    ]
    resource_spans = ResourceSpans(
        resource=Resource(
            attributes=[
                _kv("trackio.project", "otel-smolagents"),
                _kv("trackio.run", "dummy-agent"),
            ]
        ),
        scope_spans=[ScopeSpans(spans=spans)],
    )
    return ExportTraceServiceRequest(
        resource_spans=[resource_spans]
    ).SerializeToString()


def test_ingest_otlp_trace_bytes_logs_trackio_trace(temp_dir):
    result = ingest_otlp_trace_bytes(_request_bytes())

    assert result["accepted_spans"] == 1
    traces = SQLiteStorage.get_traces(
        "otel-project", run="smolagents", run_id="service-1"
    )
    assert len(traces) == 1
    assert traces[0]["run"] == "smolagents"
    assert traces[0]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    assert traces[0]["metadata"]["source"] == "opentelemetry"
    assert traces[0]["metadata"]["attributes"]["openinference.span.kind"] == "agent"


def test_otel_route_requires_write_token_and_accepts_protobuf(temp_dir):
    app, write_token = build_starlette_app_only()
    client = TestClient(app)

    unauthorized = client.post("/otel/v1/traces", content=_request_bytes())
    assert unauthorized.status_code == 400

    response = client.post(
        "/otel/v1/traces",
        content=_request_bytes(),
        headers={
            "content-type": "application/x-protobuf",
            "x-trackio-write-token": write_token,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-protobuf")
    assert (
        len(
            SQLiteStorage.get_traces(
                "otel-project", run="smolagents", run_id="service-1"
            )
        )
        == 1
    )


def test_smolagents_json_inputs_render_as_readable_requests(temp_dir):
    ingest_otlp_trace_bytes(_smolagents_request_bytes())

    traces = SQLiteStorage.get_traces(
        "otel-smolagents", run="dummy-agent", sort="step_asc"
    )
    requests = [trace["messages"][0]["content"] for trace in traces]

    assert requests == [
        "Trackio received this smolagents trace",
        "Step 1",
        "Return a short confirmation that Trackio tracing works.",
    ]
