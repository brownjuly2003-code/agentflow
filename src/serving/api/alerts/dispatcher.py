from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel, Field, model_validator

from src.serving.control_plane import get_control_plane_store

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger()

DEFAULT_ALERTS_CONFIG_PATH = Path(os.getenv("AGENTFLOW_ALERTS_FILE", "config/alerts.yaml"))


class AlertEscalationStep(BaseModel):
    level: int = Field(ge=1)
    after_minutes: int = Field(ge=0)
    webhook_url: str


class AlertFlapDetection(BaseModel):
    enabled: bool = False
    window_minutes: int = Field(default=5, ge=1)
    max_changes: int = Field(default=3, ge=1)


class AlertRule(BaseModel):
    id: str
    name: str
    tenant: str
    metric: str
    window: str
    condition: Literal["above", "below", "change_pct"]
    threshold: float
    webhook_url: str
    secret: str
    cooldown_minutes: int = 30
    active: bool = True
    created_at: datetime
    updated_at: datetime
    last_triggered_at: datetime | None = None
    escalation: list[AlertEscalationStep] = Field(default_factory=list)
    flap_detection: AlertFlapDetection = Field(default_factory=AlertFlapDetection)
    state: Literal["ok", "firing", "sustained", "resolved", "suppressed"] = "ok"
    fired_at: datetime | None = None
    resolved_at: datetime | None = None
    last_escalation_level: int = 0
    state_changes: list[datetime] = Field(default_factory=list)
    last_condition_triggered: bool = False

    @model_validator(mode="after")
    def _normalize_escalation(self) -> AlertRule:
        steps = sorted(self.escalation, key=lambda step: (step.after_minutes, step.level))
        if not steps or steps[0].after_minutes != 0:
            steps.insert(
                0,
                AlertEscalationStep(level=1, after_minutes=0, webhook_url=self.webhook_url),
            )
        else:
            first_step = steps[0]
            steps[0] = AlertEscalationStep(
                level=1,
                after_minutes=0,
                webhook_url=self.webhook_url,
            )
            if first_step.level == 1 and first_step.webhook_url == self.webhook_url:
                steps[0] = first_step
        self.escalation = steps
        self.webhook_url = self.escalation[0].webhook_url
        return self


class AlertConfig(BaseModel):
    alerts: list[AlertRule] = Field(default_factory=list)


def get_alert_config_path(app: FastAPI) -> Path:
    configured = getattr(app.state, "alert_config_path", None)
    return Path(configured) if configured else DEFAULT_ALERTS_CONFIG_PATH


def load_alerts(app: FastAPI) -> list[AlertRule]:
    store = get_control_plane_store(app)
    return [AlertRule.model_validate(record) for record in store.load_alert_rules()]


def save_alerts(app: FastAPI, alerts: list[AlertRule]) -> None:
    store = get_control_plane_store(app)
    store.save_alert_rules([alert.model_dump(mode="json") for alert in alerts])


def create_alert(
    app: FastAPI,
    *,
    name: str,
    tenant: str,
    metric: str,
    window: str,
    condition: Literal["above", "below", "change_pct"],
    threshold: float,
    webhook_url: str,
    cooldown_minutes: int,
) -> AlertRule:
    alerts = load_alerts(app)
    now = datetime.now(UTC)
    rule = AlertRule(
        id=str(uuid.uuid4()),
        name=name,
        tenant=tenant,
        metric=metric,
        window=window,
        condition=condition,
        threshold=threshold,
        webhook_url=webhook_url,
        secret=secrets.token_urlsafe(32),
        cooldown_minutes=cooldown_minutes,
        created_at=now,
        updated_at=now,
    )
    alerts.append(rule)
    save_alerts(app, alerts)
    return rule


def list_alerts(app: FastAPI, tenant: str) -> list[AlertRule]:
    return [alert for alert in load_alerts(app) if alert.tenant == tenant and alert.active]


def get_alert(app: FastAPI, alert_id: str, tenant: str) -> AlertRule | None:
    for alert in load_alerts(app):
        if alert.id == alert_id and alert.tenant == tenant and alert.active:
            return alert
    return None


def update_alert(app: FastAPI, alert_id: str, tenant: str, updates: dict) -> AlertRule | None:
    alerts = load_alerts(app)
    for index, alert in enumerate(alerts):
        if alert.id != alert_id or alert.tenant != tenant or not alert.active:
            continue
        payload = alert.model_dump(mode="python")
        payload.update(updates)
        payload["updated_at"] = datetime.now(UTC)
        updated = AlertRule.model_validate(payload)
        alerts[index] = updated
        save_alerts(app, alerts)
        return updated
    return None


def deactivate_alert(app: FastAPI, alert_id: str, tenant: str) -> bool:
    alerts = load_alerts(app)
    changed = False
    for index, alert in enumerate(alerts):
        if alert.id != alert_id or alert.tenant != tenant or not alert.active:
            continue
        payload = alert.model_dump(mode="python")
        payload["active"] = False
        payload["updated_at"] = datetime.now(UTC)
        alerts[index] = AlertRule.model_validate(payload)
        changed = True
        break
    if changed:
        save_alerts(app, alerts)
    return changed


def ensure_alert_dispatcher(app: FastAPI) -> AlertDispatcher:
    dispatcher: AlertDispatcher | None = getattr(app.state, "alert_dispatcher", None)
    if dispatcher is None:
        dispatcher = AlertDispatcher(app)
        app.state.alert_dispatcher = dispatcher
    return dispatcher


def cooldown_elapsed(alert: AlertRule, now: datetime) -> bool:
    if alert.last_triggered_at is None:
        return True
    cooldown = timedelta(minutes=alert.cooldown_minutes)
    return now - alert.last_triggered_at >= cooldown


def next_escalation_step(
    alert: AlertRule,
    now: datetime,
) -> AlertEscalationStep | None:
    if alert.fired_at is None:
        return None
    elapsed_minutes = (now - alert.fired_at).total_seconds() / 60
    due_steps = [
        step
        for step in alert.escalation
        if step.level > alert.last_escalation_level and elapsed_minutes >= step.after_minutes
    ]
    if due_steps:
        # Advance exactly one level per evaluation tick — the lowest level above
        # the current one — so every intermediate escalation target is paged.
        # Returning the highest due step (due_steps[-1]) silently skipped the
        # on-call recipients of intervening levels whenever two or more became
        # due between ticks (sparse polling, restart catch-up).
        # (audit_28_06_26.md §5 medium: escalation skips intermediate levels)
        return min(due_steps, key=lambda step: step.level)
    if (
        len(alert.escalation) == 1
        and alert.last_escalation_level == alert.escalation[0].level
        and cooldown_elapsed(alert, now)
    ):
        return alert.escalation[0]
    return None


class AlertDispatcher:
    def __init__(self, app: FastAPI, poll_interval_seconds: float = 60.0) -> None:
        self.app = app
        self.poll_interval_seconds = poll_interval_seconds
        self.backoff_seconds = [1.0, 5.0, 25.0]
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        while True:
            try:
                await self.dispatch_alerts()
            except Exception as exc:
                logger.warning("alert_dispatcher_error", error=str(exc))
            await asyncio.sleep(self.poll_interval_seconds)

    async def dispatch_alerts(self) -> int:
        from .escalation import dispatch_alert

        alerts = load_alerts(self.app)
        now = datetime.now(UTC)
        triggered = 0
        changed = False
        for index, alert in enumerate(alerts):
            if not alert.active:
                continue
            updated_alert, alert_changed, alert_triggered = await dispatch_alert(self, alert, now)
            alerts[index] = updated_alert
            triggered += alert_triggered
            changed = changed or alert_changed
        if changed:
            save_alerts(self.app, alerts)
        return triggered

    async def send_test_alert(self, alert: AlertRule) -> dict:
        from .escalation import deliver

        payload = {
            "alert_id": alert.id,
            "alert_name": alert.name,
            "metric": alert.metric,
            "threshold": alert.threshold,
            "condition": alert.condition,
            "window": alert.window,
            "triggered_at": datetime.now(UTC).isoformat(),
            "tenant": alert.tenant,
            "test": True,
        }
        return await deliver(self, alert, payload, event_type="alert.test")
