"""Alert repository of the PostgreSQL control-plane adapter.

The alert delivery history, the record-set alert-rule repository, and the
lease-column tick claim that single-flights rule evaluation across replicas
— the ``AlertRepository`` capability surface (audit F-08 split; bodies
verbatim from the pre-split ``postgres.py``).
"""

from __future__ import annotations

import json

import structlog

from .postgres_base import PostgresControlPlaneBase

logger = structlog.get_logger()


class PostgresAlertRepository(PostgresControlPlaneBase):
    """``AlertRepository`` capability of the PostgreSQL adapter."""

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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_history (
                    delivery_id, alert_id, alert_name, metric, current_value,
                    previous_value, change_pct, threshold, condition, metric_window,
                    tenant, event_type, status_code, success, error, payload,
                    triggered_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, now())
                """,
                (
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
                ),
            )

    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            result = conn.execute(
                """
                SELECT delivery_id, alert_id, alert_name, metric, current_value,
                       previous_value, change_pct, threshold, condition,
                       metric_window AS window,
                       tenant, event_type, status_code, success, error, payload,
                       triggered_at
                FROM alert_history
                WHERE alert_id = %s
                ORDER BY triggered_at DESC
                LIMIT %s
                """,
                (alert_id, limit),
            )
            columns = [description.name for description in result.description]
            records = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
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
        with self._connect() as conn:
            rows = conn.execute("SELECT record FROM alert_rules ORDER BY position ASC").fetchall()
        return [json.loads(record) for (record,) in rows]

    def save_alert_rules(self, rules: list[dict]) -> None:
        self._replace_record_set("alert_rules", rules)

    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alert_rules
                SET tick_lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s
                  AND (tick_lease_expires_at IS NULL OR tick_lease_expires_at <= now())
                """,
                (lease_seconds, rule_id),
            )
            # rowcount 0 = another replica holds this rule's tick (or the rule
            # row is gone — either way, nothing to evaluate here).
            return bool(cursor.rowcount == 1)

    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
        with self._connect() as conn:
            if record is None:
                conn.execute(
                    "UPDATE alert_rules SET tick_lease_expires_at = NULL WHERE id = %s",
                    (rule_id,),
                )
                return
            # State advance and claim release in the same transaction
            # (ADR 0010 §2).
            conn.execute(
                """
                UPDATE alert_rules
                SET record = %s, tick_lease_expires_at = NULL
                WHERE id = %s
                """,
                (json.dumps(record, sort_keys=True), rule_id),
            )
