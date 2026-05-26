"""Per-tenant API-usage table — DuckDB schema + read/write helpers.

Extracted from `middleware.py` per Kimi audit L-C4 (2026-05-25): DB
schema management and INSERT/SELECT helpers don't belong alongside the
ASGI middleware. Imported lazily from `AuthManager` to avoid an import
cycle with `manager.py`.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import structlog

from src.serving.duckdb_connection import connect_duckdb

if TYPE_CHECKING:
    from .manager import AuthManager, TenantKey


def ensure_usage_table(manager: AuthManager) -> None:
    for attempt in range(10):
        try:
            conn = connect_duckdb(manager.db_path)
        except duckdb.IOException as exc:
            if (
                os.getenv("AGENTFLOW_USAGE_DB_PATH") is None
                and manager.db_path.name == "agentflow_api.duckdb"
            ):
                from src.serving.api import auth as auth_package

                fallback_path = (
                    Path(os.getenv("TEMP", "."))
                    / f"agentflow_api_{os.getpid()}_{time.time_ns()}.duckdb"
                )
                auth_package.logger.warning(
                    "usage_db_path_fallback",
                    original=str(manager.db_path),
                    fallback=str(fallback_path),
                    error=str(exc),
                )
                manager.db_path = fallback_path
                conn = connect_duckdb(manager.db_path)
            else:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
            continue

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_usage (
                    tenant TEXT,
                    key_name TEXT,
                    endpoint TEXT,
                    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info('api_usage')").fetchall()}
            if "key_id" not in columns:
                conn.execute("ALTER TABLE api_usage ADD COLUMN key_id TEXT")
            if "key_slot" not in columns:
                conn.execute("ALTER TABLE api_usage ADD COLUMN key_slot TEXT")
            return
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()


def record_usage(manager: AuthManager, tenant_key: TenantKey, endpoint: str) -> None:
    payload = {
        "event_type": "api_usage",
        "tenant": tenant_key.tenant,
        "key_name": tenant_key.name,
        "endpoint": endpoint,
        "key_id": tenant_key.key_id,
        "key_slot": tenant_key.matched_slot,
    }
    inserted = False
    for attempt in range(10):
        try:
            conn = connect_duckdb(manager.db_path)
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
            continue

        try:
            conn.execute(
                """
                INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    tenant_key.tenant,
                    tenant_key.name,
                    endpoint,
                    tenant_key.key_id,
                    tenant_key.matched_slot,
                ],
            )
            inserted = True
            break
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()

    # Audit publish is intentionally outside the DB retry loop: a publish
    # failure must not trigger another INSERT (H-C3 / audit_kimi_25_05_26).
    if inserted:
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
    conn = connect_duckdb(manager.db_path)
    try:
        rows = conn.execute(
            """
            SELECT tenant, COUNT(*) AS requests_last_24h
            FROM api_usage
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            GROUP BY tenant
            ORDER BY tenant
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {"tenant": tenant, "requests_last_24h": requests_last_24h}
        for tenant, requests_last_24h in rows
    ]
