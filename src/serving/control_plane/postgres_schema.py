"""DDL and versioned-migration ledger of the PostgreSQL control-plane store.

``_SCHEMA_STATEMENTS`` is migration 1 (the pre-versioning baseline);
``_MIGRATIONS`` is the dense monotonic list ``postgres_base`` applies under
the transaction-scoped advisory lock (audit F-08 split; moved verbatim from
the pre-split ``postgres.py``).
"""

from __future__ import annotations

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS webhook_delivery_queue (
        webhook_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        tenant TEXT,
        event_type TEXT,
        body TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ,
        last_status_code INTEGER,
        last_error TEXT,
        lease_expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (webhook_id, event_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS webhook_delivery_queue_due_idx
        ON webhook_delivery_queue (created_at) WHERE status = 'pending'
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        delivery_id TEXT,
        webhook_id TEXT,
        event_id TEXT,
        event_type TEXT,
        attempt INTEGER,
        status_code INTEGER,
        success BOOLEAN,
        error TEXT,
        delivered_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS webhook_deliveries_webhook_idx
        ON webhook_deliveries (webhook_id, delivered_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_history (
        delivery_id TEXT,
        alert_id TEXT,
        alert_name TEXT,
        metric TEXT,
        current_value DOUBLE PRECISION,
        previous_value DOUBLE PRECISION,
        change_pct DOUBLE PRECISION,
        threshold DOUBLE PRECISION,
        condition TEXT,
        metric_window TEXT,
        tenant TEXT,
        event_type TEXT,
        status_code INTEGER,
        success BOOLEAN,
        error TEXT,
        payload TEXT,
        triggered_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS alert_history_alert_idx
        ON alert_history (alert_id, triggered_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_registrations (
        id TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_rules (
        id TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        record TEXT NOT NULL,
        tick_lease_expires_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outbox (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        topic TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        sent_at TIMESTAMPTZ,
        status TEXT DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        next_attempt_at TIMESTAMPTZ DEFAULT now(),
        last_error TEXT,
        lease_expires_at TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS outbox_due_idx
        ON outbox (created_at) WHERE status = 'pending'
    """,
    """
    CREATE TABLE IF NOT EXISTS dead_letter_events (
        event_id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        event_type TEXT,
        payload TEXT,
        failure_reason TEXT,
        failure_detail TEXT,
        received_at TIMESTAMPTZ,
        retry_count INTEGER DEFAULT 0,
        last_retried_at TIMESTAMPTZ,
        status TEXT DEFAULT 'failed'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ops_exception_triage (
        item_id TEXT PRIMARY KEY,
        tenant_id TEXT,
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        first_seen_at TIMESTAMPTZ,
        last_seen_at TIMESTAMPTZ,
        resolved_at TIMESTAMPTZ,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_usage (
        tenant TEXT,
        key_name TEXT,
        endpoint TEXT,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        key_id TEXT,
        key_slot TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS api_usage_ts_idx ON api_usage (ts)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_sessions (
        request_id TEXT PRIMARY KEY,
        tenant TEXT,
        key_name TEXT,
        endpoint TEXT,
        method TEXT,
        status_code INTEGER,
        duration_ms DOUBLE PRECISION,
        cache_hit BOOLEAN,
        entity_type TEXT,
        metric_name TEXT,
        query_engine TEXT,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        entity_id TEXT,
        query_text TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS api_sessions_ts_idx ON api_sessions (ts)
    """,
)

# --- versioned migrations (audit P1-1) ---------------------------------------
#
# The ledger table is created outside the migration list (it must exist to
# read the current version). Each migration is (version, description,
# statements); versions are dense and monotonic from 1 — enforced at import,
# because a gap or duplicate silently skips or repeats DDL. Migration 1 is
# the pre-versioning baseline: pure IF NOT EXISTS, so a store that predates
# the ledger upgrades by a no-op pass and gets stamped. Later migrations may
# use ALTER and rely on running exactly once.

_SCHEMA_VERSION_DDL = """
    CREATE TABLE IF NOT EXISTS control_plane_schema_version (
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""

_MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "baseline: six control-plane state classes (ADR 0010 slice 5)", _SCHEMA_STATEMENTS),
    (
        2,
        "webhook_delivery_queue.last_outcome_id — idempotent outcome write (P3)",
        ("ALTER TABLE webhook_delivery_queue ADD COLUMN IF NOT EXISTS last_outcome_id TEXT",),
    ),
)

if tuple(version for version, _, _ in _MIGRATIONS) != tuple(range(1, len(_MIGRATIONS) + 1)):
    raise RuntimeError(
        "_MIGRATIONS versions must be dense and monotonic starting at 1: "
        f"{[version for version, _, _ in _MIGRATIONS]}"
    )

# Transaction-scoped advisory lock serializing concurrent replicas' migration
# runs. Any fixed 64-bit value works; this one spells 'AGFLOWCP'.
_MIGRATION_LOCK_KEY = 0x41474C4F57435031 % (2**63)
