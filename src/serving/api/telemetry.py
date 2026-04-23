import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from src.processing.tracing import telemetry_disabled
from src.serving.api.middleware.tracing import configure_server_request_span

_tracer_provider: TracerProvider | None = None
_httpx_instrumented = False
_registered_exporters: set[int] = set()


def setup_telemetry(
    app: FastAPI,
    span_exporter: SpanExporter | None = None,
) -> None:
    global _httpx_instrumented
    global _tracer_provider

    if telemetry_disabled():
        return

    if _tracer_provider is None:
        _tracer_provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": os.getenv("OTEL_SERVICE_NAME", "agentflow-api"),
                }
            )
        )
        default_exporter = span_exporter
        if default_exporter is None:
            otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            if otlp_endpoint:
                default_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
                _tracer_provider.add_span_processor(BatchSpanProcessor(default_exporter))
        else:
            _tracer_provider.add_span_processor(SimpleSpanProcessor(default_exporter))
            _registered_exporters.add(id(default_exporter))
        trace.set_tracer_provider(_tracer_provider)
    elif span_exporter is not None and id(span_exporter) not in _registered_exporters:
        _tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        _registered_exporters.add(id(span_exporter))

    if not getattr(app.state, "telemetry_instrumented", False):
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_tracer_provider,
            server_request_hook=configure_server_request_span,
        )
        app.state.telemetry_instrumented = True

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=_tracer_provider)
        _httpx_instrumented = True
