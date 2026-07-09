"""Prometheus counters exposed by the serving API.

Both metrics are scraped from the `/metrics` endpoint mounted in
`src.serving.api.main` and backed by the dashboards under
`infrastructure/observability/grafana/agentflow-api-health.json`.

* ``agentflow_auth_failures_total`` — referenced by
  ``docs/runbooks/auth-401-spike.md`` (Detection step 1).
* ``agentflow_http_requests_total`` — referenced by
  ``docs/runbooks/api-5xx-spike.md`` (Symptom + Detection step 1).
"""

from __future__ import annotations

from prometheus_client import Counter

# Label values are documented in docs/runbooks/auth-401-spike.md § Detection.
AUTH_FAILURES = Counter(
    "agentflow_auth_failures_total",
    "API authentication failures by reason.",
    labelnames=("reason",),
)

HTTP_REQUESTS = Counter(
    "agentflow_http_requests_total",
    "HTTP requests served by the API, labelled by method, route template, and status code.",
    labelnames=("method", "route", "status"),
)

# Usage accounting is a side-channel: a dropped row must never fail the request
# it was counting. Non-zero means per-tenant request counters under-report.
USAGE_RECORD_FAILURES = Counter(
    "agentflow_usage_record_failures_total",
    "Authenticated requests served without their api_usage row being written.",
)

# Backpressure, not failure: the writer's queue was full, so the row was shed
# rather than made to stall the request it was counting. Sustained non-zero
# means the writer cannot keep up with the request rate.
USAGE_ROWS_DROPPED = Counter(
    "agentflow_usage_rows_dropped_total",
    "api_usage rows dropped because the off-path writer queue was full.",
)
