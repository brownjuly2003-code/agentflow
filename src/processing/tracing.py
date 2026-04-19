from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject


def telemetry_disabled() -> bool:
    return os.getenv("OTEL_SDK_DISABLED", "").lower() == "true"


def inject_trace_to_kafka_headers(
    headers: Mapping[str, bytes] | None = None,
) -> dict[str, bytes]:
    injected_headers = dict(headers or {})
    if telemetry_disabled():
        return injected_headers

    carrier: dict[str, str] = {}
    inject(carrier)
    for key, value in carrier.items():
        injected_headers[key] = value.encode("utf-8")
    return injected_headers


def extract_trace_from_kafka_headers(
    headers: Mapping[str, bytes] | Sequence[tuple[str, bytes]] | None,
) -> Context:
    if telemetry_disabled() or headers is None:
        return extract({})

    items = headers.items() if isinstance(headers, Mapping) else headers
    carrier = {
        str(key): value.decode("utf-8")
        for key, value in items
        if isinstance(value, bytes)
    }
    return extract(carrier)
