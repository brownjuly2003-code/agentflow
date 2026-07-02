"""Control-plane state store (ADR 0009 / ADR 0010).

``ControlPlaneStore`` is the port; ``EmbeddedControlPlaneStore`` (DuckDB,
single-replica default) is the shipped adapter; ``PostgresControlPlaneStore``
(scale profile) arrives with ADR 0010 rollout slice 5. Resolve the app's
store via ``get_control_plane_store`` — never through ``query_engine._conn``.
"""

from .embedded import (
    EmbeddedControlPlaneStore,
    ensure_alert_history_table,
    ensure_webhook_deliveries_table,
    ensure_webhook_delivery_queue_table,
)
from .store import (
    CONTROL_PLANE_STORE_ENV,
    ControlPlaneStore,
    WebhookQueueRow,
    get_control_plane_store,
)

__all__ = [
    "CONTROL_PLANE_STORE_ENV",
    "ControlPlaneStore",
    "EmbeddedControlPlaneStore",
    "WebhookQueueRow",
    "ensure_alert_history_table",
    "ensure_webhook_deliveries_table",
    "ensure_webhook_delivery_queue_table",
    "get_control_plane_store",
]
