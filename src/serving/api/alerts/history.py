from __future__ import annotations

import json
from datetime import UTC
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from .dispatcher import AlertRule


def ensure_alert_history_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_history (
            delivery_id VARCHAR,
            alert_id VARCHAR,
            alert_name VARCHAR,
            metric VARCHAR,
            current_value DOUBLE,
            previous_value DOUBLE,
            change_pct DOUBLE,
            threshold DOUBLE,
            condition VARCHAR,
            metric_window VARCHAR,
            tenant VARCHAR,
            event_type VARCHAR,
            status_code INTEGER,
            success BOOLEAN,
            error TEXT,
            payload JSON,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_alert_history(conn: duckdb.DuckDBPyConnection, alert_id: str) -> list[dict]:
    ensure_alert_history_table(conn)
    cursor = conn.execute(
        """
        SELECT delivery_id, alert_id, alert_name, metric, current_value,
               previous_value, change_pct, threshold, condition,
               metric_window AS window,
               tenant, event_type, status_code, success, error, payload, triggered_at
        FROM alert_history
        WHERE alert_id = ?
        ORDER BY triggered_at DESC
        LIMIT 20
        """,
        [alert_id],
    )
    columns = [description[0] for description in cursor.description]
    records = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
    for record in records:
        payload = record.get("payload")
        if isinstance(payload, str):
            try:
                record["payload"] = json.loads(payload)
            except json.JSONDecodeError:
                pass
    return records


def log_alert_history(
    conn: duckdb.DuckDBPyConnection,
    *,
    delivery_id: str,
    alert: AlertRule,
    metric: str,
    current_value: float | None,
    previous_value: float | None,
    change_pct: float | None,
    threshold: float,
    condition: str,
    window: str,
    event_type: str,
    status_code: int | None,
    success: bool,
    error: str | None,
    payload: dict,
) -> None:
    from src.serving.api import alert_dispatcher as compat

    ensure_alert_history_table(conn)
    conn.execute(
        """
        INSERT INTO alert_history (
            delivery_id, alert_id, alert_name, metric, current_value,
            previous_value, change_pct, threshold, condition, metric_window,
            tenant, event_type, status_code, success, error, payload, triggered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            delivery_id,
            alert.id,
            alert.name,
            metric,
            current_value,
            previous_value,
            change_pct,
            threshold,
            condition,
            window,
            alert.tenant,
            event_type,
            status_code,
            success,
            error,
            json.dumps(payload, sort_keys=True),
            compat.datetime.now(UTC),
        ],
    )
