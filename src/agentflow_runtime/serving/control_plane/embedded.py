"""Embedded (DuckDB) control-plane store — the single-replica default profile.

Extracted from ``webhook_dispatcher`` in ADR 0010 rollout slice 1: the table
DDL, SQL shapes and catalog-DDL-lock behavior are byte-compatible with the
pre-port code, so existing deployments and the pinned regression suites see
no behavior change.

"Claims" here are trivially exclusive: this store is only ever used by one
process (the Helm chart refuses multi-replica renders on the embedded
profile), so ``claim_due_webhook_deliveries`` is a plain due-scan without
marking rows in-flight. The PostgreSQL adapter (slice 5) implements the same
contract with ``FOR UPDATE SKIP LOCKED`` plus a lease column.

Audit F-08 split the former single-module adapter into bounded capability
repositories — ``embedded_webhook``, ``embedded_alert``,
``embedded_outbox_replay``, ``embedded_usage_audit`` over the shared
``embedded_base`` plumbing — with method bodies moved verbatim. This module
stays the assembly point and the only public import surface: consumers and
tests keep importing everything from here, and the monkeypatch seams below
(``connect_duckdb``, ``duckdb``, ``time``, ``catalog_ddl_lock``,
``_USAGE_CONNECTIONS``) keep their pre-split names.
"""

from __future__ import annotations

# Patch seams, not dead imports: tests reach these through this module's
# namespace — `embedded.connect_duckdb` (flaky-connection injection, resolved
# late by `embedded_base._usage_connection`), `embedded.duckdb.connect`,
# `embedded.time.sleep`, and the `catalog_ddl_lock is` identity check.
import time  # noqa: F401

import duckdb  # noqa: F401

from agentflow_runtime.db_concurrency import catalog_ddl_lock  # noqa: F401
from agentflow_runtime.serving.duckdb_connection import connect_duckdb  # noqa: F401

from .embedded_alert import EmbeddedAlertRepository, ensure_alert_history_table
from .embedded_base import (
    _USAGE_CONNECTIONS,
    _drop_usage_connection,
    _usage_connection,
    close_usage_connections,
)
from .embedded_outbox_replay import (
    EmbeddedOutboxReplayRepository,
    ensure_dead_letter_table,
    ensure_outbox_table,
    ensure_triage_table,
)
from .embedded_usage_audit import (
    EmbeddedUsageAuditRepository,
    ensure_api_sessions_table,
    ensure_api_usage_table,
)
from .embedded_webhook import (
    EmbeddedWebhookRepository,
    ensure_webhook_deliveries_table,
    ensure_webhook_delivery_queue_table,
)

__all__ = [
    "_USAGE_CONNECTIONS",
    "EmbeddedAlertRepository",
    "EmbeddedControlPlaneStore",
    "EmbeddedOutboxReplayRepository",
    "EmbeddedUsageAuditRepository",
    "EmbeddedWebhookRepository",
    "_drop_usage_connection",
    "_usage_connection",
    "close_usage_connections",
    "ensure_alert_history_table",
    "ensure_api_sessions_table",
    "ensure_api_usage_table",
    "ensure_dead_letter_table",
    "ensure_outbox_table",
    "ensure_triage_table",
    "ensure_webhook_deliveries_table",
    "ensure_webhook_delivery_queue_table",
]


class EmbeddedControlPlaneStore(
    EmbeddedWebhookRepository,
    EmbeddedAlertRepository,
    EmbeddedOutboxReplayRepository,
    EmbeddedUsageAuditRepository,
):
    """Control-plane state on the embedded serving DuckDB connection (queue,
    log and history tables) plus the YAML-backed alert-rule repository.

    ``conn_provider`` is resolved per call (not captured once): tests and the
    lifespan may swap ``app.state.query_engine``, and the store must follow
    the live connection exactly like the pre-port ``_conn`` lookups did.
    ``alert_rules_path_provider`` is resolved the same way — the alert config
    path is per-app configurable (``app.state.alert_config_path``) and tests
    swap it per case.
    """
