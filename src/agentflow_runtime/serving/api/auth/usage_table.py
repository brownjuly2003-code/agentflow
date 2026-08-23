"""Per-tenant API-usage accounting — thin wrappers over `AuthManager.store`.

Extracted from `middleware.py` per audit L-C4 (2026-05-25): DB
schema management and INSERT/SELECT helpers don't belong alongside the
ASGI middleware. Imported lazily from `AuthManager` to avoid an import
cycle with `manager.py`. The actual DuckDB schema/SQL now lives behind the
`ControlPlaneStore` port (ADR 0010 slice 4, `control_plane/embedded.py`) —
these functions keep their pre-port signatures because `AuthManager` and
tests call them directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .manager import AuthManager, TenantKey


def ensure_usage_table(manager: AuthManager) -> None:
    manager.store.ensure_usage_schema()


def record_usage(manager: AuthManager, tenant_key: TenantKey, endpoint: str) -> None:
    payload = {
        "event_type": "api_usage",
        "tenant": tenant_key.tenant,
        "key_name": tenant_key.name,
        "endpoint": endpoint,
        "key_id": tenant_key.key_id,
        "key_slot": tenant_key.matched_slot,
    }
    # Audit publish is intentionally outside the DB retry loop (delegated to
    # the store below): a publish failure must not trigger another INSERT
    # (H-C3 / audit-2026-05). If the insert never succeeds, record_api_usage
    # raises and this function never reaches the publish call.
    manager.store.record_api_usage(
        tenant=tenant_key.tenant,
        key_name=tenant_key.name,
        endpoint=endpoint,
        key_id=tenant_key.key_id,
        key_slot=tenant_key.matched_slot,
    )
    try:
        manager.audit_publisher.publish(payload)
    except Exception:
        structlog.get_logger(__name__).warning(
            "audit_publish_failed",
            tenant=tenant_key.tenant,
            endpoint=endpoint,
            key_id=tenant_key.key_id,
            exc_info=True,
        )


def usage_by_tenant(manager: AuthManager) -> list[dict]:
    return manager.store.get_usage_by_tenant()
