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

# The webhook dispatcher's settle watermark rests on an operator invariant:
# AGENTFLOW_WEBHOOK_SETTLE_SECONDS must exceed writer stamp-to-visibility lag +
# writer<->DB clock skew. A violation is otherwise SILENT — a row that becomes
# visible with a (processed_at, event_id) already behind the strict keyset
# frontier is excluded by every future forward scan and never delivered. This
# counter is incremented by the dispatcher's sampled behind-frontier probe for
# each such never-handed-out row it observes; sustained non-zero means settle is
# set below the writers' true visibility lag and webhook deliveries are being
# dropped (raise AGENTFLOW_WEBHOOK_SETTLE_SECONDS). Flat at 0 is healthy.
WEBHOOK_SETTLE_VIOLATIONS = Counter(
    "agentflow_webhook_settle_violations_total",
    "Journal rows observed strictly behind the webhook scan frontier yet never "
    "handed out — a violated settle invariant (settle < write-visibility lag).",
)
