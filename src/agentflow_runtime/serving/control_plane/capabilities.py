"""Narrow capability ports over the legacy control-plane facade.

Adapters keep implementing ``ControlPlaneStore`` for compatibility. New
consumers depend on one of these protocols so a webhook change cannot couple
them to alert, replay, or usage semantics.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from .store import (
    OutboxEntry,
    TriageState,
    UsageRow,
    WebhookQueueRow,
    get_control_plane_store,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


@runtime_checkable
class WebhookRepository(Protocol):
    def enqueue_webhook_delivery(
        self,
        *,
        webhook_id: str,
        event_id: str,
        tenant: str,
        event_type: str,
        body: str,
    ) -> bool: ...

    def claim_due_webhook_deliveries(self, *, limit: int) -> list[WebhookQueueRow]: ...

    def record_webhook_delivery_outcome(
        self,
        *,
        webhook_id: str,
        event_id: str,
        success: bool,
        status_code: int | None,
        error: str | None,
        max_attempts: int,
        backoff_seconds: Sequence[float],
        delivery_id: str | None = None,
    ) -> None: ...

    def park_webhook_delivery(self, *, webhook_id: str, event_id: str, error: str) -> None: ...

    def log_webhook_delivery(
        self,
        *,
        delivery_id: str,
        webhook_id: str,
        event_id: str,
        event_type: str,
        attempt: int,
        status_code: int | None,
        success: bool,
        error: str | None,
    ) -> None: ...

    def get_webhook_delivery_logs(self, webhook_id: str, *, limit: int = 20) -> list[dict]: ...

    def load_webhook_registrations(self) -> list[dict]: ...

    def save_webhook_registrations(self, registrations: list[dict]) -> None: ...

    def list_dead_webhook_deliveries(
        self, tenant_id: str | None = None, *, limit: int | None = None
    ) -> list[dict]: ...


@runtime_checkable
class AlertRepository(Protocol):
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
    ) -> None: ...

    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]: ...

    def load_alert_rules(self) -> list[dict]: ...

    def save_alert_rules(self, rules: list[dict]) -> None: ...

    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool: ...

    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None: ...


@runtime_checkable
class OutboxReplayRepository(Protocol):
    def ensure_outbox_schema(self) -> None: ...

    def claim_due_outbox_entries(self, *, limit: int = 100) -> list[OutboxEntry]: ...

    def get_pending_outbox_entry(self, outbox_id: str) -> OutboxEntry | None: ...

    def mark_outbox_sent(self, *, outbox_id: str, event_id: str) -> None: ...

    def schedule_outbox_retry(
        self,
        *,
        outbox_id: str,
        event_id: str,
        retry_count: int,
        error_message: str,
        max_retries: int,
    ) -> None: ...

    def enqueue_outbox_replay(
        self,
        *,
        outbox_id: str,
        event_id: str,
        payload: dict,
        topic: str,
        retry_count: int,
        replayed_at: datetime,
    ) -> None: ...

    def get_dead_letter_event_for_replay(self, event_id: str) -> dict | None: ...

    def dismiss_dead_letter_event(self, event_id: str) -> None: ...

    def dead_letter_event_exists(self, event_id: str, tenant_id: str) -> bool: ...

    def get_dead_letter_event(self, event_id: str, tenant_id: str) -> dict | None: ...

    def list_dead_letter_events(
        self,
        *,
        tenant_id: str,
        reason: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]: ...

    def get_dead_letter_stats(self, tenant_id: str) -> dict: ...

    def list_dead_letter_events_for_inbox(
        self, tenant_id: str, *, limit: int | None = None
    ) -> list[dict]: ...

    def list_stuck_replay_dead_letter_events(
        self, tenant_id: str, *, older_than_seconds: float
    ) -> list[dict]: ...

    def count_dead_letter_manual_actions(self, tenant_id: str) -> int: ...

    def ensure_triage_schema(self) -> None: ...

    def list_triage_states(
        self, *, tenant_id: str, source: str | None = None
    ) -> list[TriageState]: ...

    def upsert_triage_finding(
        self, *, item_id: str, tenant_id: str, source: str, seen_at: datetime
    ) -> None: ...

    def auto_resolve_missing_triage_findings(
        self,
        *,
        tenant_id: str,
        source: str,
        seen_item_ids: Sequence[str],
        resolved_at: datetime,
    ) -> None: ...

    def set_triage_state(
        self,
        *,
        item_id: str,
        tenant_id: str,
        status: str,
        note: str | None = None,
    ) -> bool: ...

    def count_triage_manual_actions(self, tenant_id: str) -> int: ...

    def list_dead_webhook_deliveries(
        self, tenant_id: str | None = None, *, limit: int | None = None
    ) -> list[dict]: ...


@runtime_checkable
class UsageAuditRepository(Protocol):
    def ensure_usage_schema(self) -> None: ...

    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None: ...

    def record_api_usage_batch(self, rows: Sequence[UsageRow]) -> None: ...

    def get_usage_by_tenant(self) -> list[dict]: ...

    def get_usage_by_key(self) -> dict[tuple[str, str], int]: ...

    def get_old_key_usage_by_key_id(self) -> dict[str, int]: ...

    def record_api_session(self, request_id: str, record: dict) -> None: ...

    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict: ...

    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict: ...

    def prune_api_sessions(self, *, older_than_days: int) -> int: ...

    def delete_tenant_api_sessions(self, *, tenant: str) -> int: ...

    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict: ...

    def get_latency_analytics(self, *, window: str = "24h") -> dict: ...

    def get_anomalies(self, *, window: str = "24h") -> dict: ...

    def get_queries_per_second_last_minute(self) -> float: ...


def get_webhook_repository(app: FastAPI) -> WebhookRepository:
    return cast(WebhookRepository, get_control_plane_store(app))


def get_alert_repository(app: FastAPI) -> AlertRepository:
    return cast(AlertRepository, get_control_plane_store(app))


def get_outbox_replay_repository(app: FastAPI) -> OutboxReplayRepository:
    return cast(OutboxReplayRepository, get_control_plane_store(app))


def get_usage_audit_repository(app: FastAPI) -> UsageAuditRepository:
    return cast(UsageAuditRepository, get_control_plane_store(app))
