"""Control-plane state store (ADR 0009 / ADR 0010).

``ControlPlaneStore`` is the port; ``EmbeddedControlPlaneStore`` (DuckDB,
single-replica default) and ``PostgresControlPlaneStore`` (scale profile,
ADR 0010 rollout slice 5) are the adapters. Resolve the app's store via
``get_control_plane_store`` — never through ``query_engine._conn``.
``PostgresControlPlaneStore`` is intentionally NOT re-exported here: it
imports lazily (psycopg is an optional dependency, the ``redis`` pattern),
so reach it via ``agentflow_runtime.serving.control_plane.postgres`` only when configured.
"""

from .capabilities import (
    AlertRepository,
    OutboxReplayRepository,
    UsageAuditRepository,
    WebhookRepository,
    get_alert_repository,
    get_outbox_replay_repository,
    get_usage_audit_repository,
    get_webhook_repository,
)
from .embedded import (
    EmbeddedControlPlaneStore,
    ensure_alert_history_table,
    ensure_api_sessions_table,
    ensure_api_usage_table,
    ensure_dead_letter_table,
    ensure_outbox_table,
    ensure_triage_table,
    ensure_webhook_deliveries_table,
    ensure_webhook_delivery_queue_table,
)
from .store import (
    CONTROL_PLANE_PG_DSN_ENV,
    CONTROL_PLANE_STORE_ENV,
    ControlPlaneStore,
    OutboxEntry,
    TriageState,
    WebhookQueueRow,
    control_plane_store_kind,
    get_control_plane_store,
    stuck_replay_threshold_seconds,
)

__all__ = [
    "CONTROL_PLANE_PG_DSN_ENV",
    "CONTROL_PLANE_STORE_ENV",
    "AlertRepository",
    "ControlPlaneStore",
    "EmbeddedControlPlaneStore",
    "OutboxEntry",
    "OutboxReplayRepository",
    "TriageState",
    "UsageAuditRepository",
    "WebhookRepository",
    "WebhookQueueRow",
    "control_plane_store_kind",
    "ensure_alert_history_table",
    "ensure_api_sessions_table",
    "ensure_api_usage_table",
    "ensure_dead_letter_table",
    "ensure_outbox_table",
    "ensure_triage_table",
    "ensure_webhook_deliveries_table",
    "ensure_webhook_delivery_queue_table",
    "get_control_plane_store",
    "get_alert_repository",
    "get_outbox_replay_repository",
    "get_usage_audit_repository",
    "get_webhook_repository",
    "stuck_replay_threshold_seconds",
]
