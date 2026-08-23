"""Alert repository of the embedded (DuckDB) control-plane adapter.

The alert delivery history, the YAML-backed alert-rule repository, and the
single-replica tick claim — the ``AlertRepository`` capability surface
(audit F-08 split; bodies verbatim from the pre-split ``embedded.py``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import duckdb
import structlog

from agentflow_runtime.db_concurrency import catalog_ddl_lock

from .embedded_base import EmbeddedControlPlaneBase

logger = structlog.get_logger()

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def ensure_alert_history_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from alerts/history.py in ADR 0010 slice 2; same
    # catalog-DDL-lock discipline as its ensure_webhook_* siblings above
    # (audit_30 A2 follow-up: #120 offload race).
    with catalog_ddl_lock:
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


class EmbeddedAlertRepository(EmbeddedControlPlaneBase):
    """``AlertRepository`` capability of the embedded adapter."""

    # --- alert delivery history -----------------------------------------------

    def log_alert_delivery(
        self,
        *,
        delivery_id: str,
        alert_id: str,
        alert_name: str,
        tenant: str,
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
        conn = self._conn
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
                alert_id,
                alert_name,
                metric,
                current_value,
                previous_value,
                change_pct,
                threshold,
                condition,
                window,
                tenant,
                event_type,
                status_code,
                success,
                error,
                json.dumps(payload, sort_keys=True),
                datetime.now(UTC),
            ],
        )

    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]:
        # A dedicated cursor per read — not the shared connection — keeps
        # concurrent reads on worker threads (run_in_threadpool) from colliding
        # on the connection. (audit_30_06_26.md A2)
        cursor = self._conn.cursor()
        try:
            ensure_alert_history_table(cursor)
            result = cursor.execute(
                """
                SELECT delivery_id, alert_id, alert_name, metric, current_value,
                       previous_value, change_pct, threshold, condition,
                       metric_window AS window,
                       tenant, event_type, status_code, success, error, payload, triggered_at
                FROM alert_history
                WHERE alert_id = ?
                ORDER BY triggered_at DESC
                LIMIT ?
                """,
                [alert_id, limit],
            )
            columns = [description[0] for description in result.description]
            records = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
        finally:
            cursor.close()
        for record in records:
            payload = record.get("payload")
            if isinstance(payload, str):
                try:
                    record["payload"] = json.loads(payload)
                except json.JSONDecodeError:
                    pass
        return records

    # --- alert rule repository (mutable runtime state) ------------------------

    def load_alert_rules(self) -> list[dict]:
        path = self._alert_rules_path
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        data = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
        return list((data or {}).get("alerts", []))

    def save_alert_rules(self, rules: list[dict]) -> None:
        path = self._alert_rules_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"alerts": rules}
        content = (
            yaml.safe_dump(payload, sort_keys=False)
            if yaml is not None
            else json.dumps(payload, indent=2)
        )
        path.write_text(content, encoding="utf-8", newline="\n")

    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
        # One process, one dispatcher loop: every claim is granted — the same
        # degenerate exclusivity as claim_due_webhook_deliveries above. The
        # PostgreSQL adapter takes a real lease here (ADR 0010 §2).
        return True

    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
        if record is None:
            # Nothing advanced and embedded claims hold no lease to release.
            return
        rules = self.load_alert_rules()
        for index, existing in enumerate(rules):
            if existing.get("id") == rule_id:
                rules[index] = record
                break
        else:
            rules.append(record)
        self.save_alert_rules(rules)
