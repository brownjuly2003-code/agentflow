from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from src.serving.api.webhook_dispatcher import _event_body, _signature

from .evaluator import evaluate_rule
from .history import ensure_alert_history_table, log_alert_history

if TYPE_CHECKING:
    from .dispatcher import AlertDispatcher, AlertRule


async def dispatch_alert(
    dispatcher: AlertDispatcher,
    alert: AlertRule,
    now: datetime,
) -> tuple[AlertRule, bool, int]:
    from src.serving.api import alert_dispatcher as compat

    from .dispatcher import next_escalation_step

    evaluation = evaluate_rule(dispatcher, alert, now)
    current_triggered = bool(evaluation["triggered"])
    alert_changed = False
    triggered = 0

    if alert.flap_detection.enabled:
        previous_count = len(alert.state_changes)
        flap_window = timedelta(minutes=alert.flap_detection.window_minutes)
        alert.state_changes = [
            state_change
            for state_change in alert.state_changes
            if now - state_change <= flap_window
        ]
        alert_changed = alert_changed or len(alert.state_changes) != previous_count

    if alert.state == "suppressed" and (
        not alert.flap_detection.enabled
        or len(alert.state_changes) <= alert.flap_detection.max_changes
    ):
        alert.state = "ok"
        alert.fired_at = None
        alert.resolved_at = now if not current_triggered else None
        alert.last_escalation_level = 0
        alert.last_condition_triggered = False
        alert_changed = True

    state_changed = current_triggered != alert.last_condition_triggered
    if state_changed and alert.flap_detection.enabled:
        alert.state_changes.append(now)
        alert_changed = True
        if len(alert.state_changes) > alert.flap_detection.max_changes:
            alert.state = "suppressed"
            alert.fired_at = None
            alert.resolved_at = now if not current_triggered else None
            alert.last_escalation_level = 0
            alert.last_condition_triggered = current_triggered
            alert.updated_at = now
            compat.logger.warning(
                "alert_flapping_suppressed",
                alert_id=alert.id,
                alert_name=alert.name,
                changes=len(alert.state_changes),
                window_minutes=alert.flap_detection.window_minutes,
            )
            return alert, True, 0

    if alert.state == "suppressed":
        alert.last_condition_triggered = current_triggered
        alert.updated_at = now
        return alert, True, 0

    if current_triggered and alert.fired_at is None:
        alert.fired_at = now
        alert.resolved_at = None
        alert.state = "firing"
        alert.last_escalation_level = 1
        payload = {
            "alert_id": alert.id,
            "alert_name": alert.name,
            "status": "firing",
            "metric": alert.metric,
            "current_value": evaluation["current_value"],
            "threshold": alert.threshold,
            "condition": alert.condition,
            "window": alert.window,
            "triggered_at": now.isoformat(),
            "fired_at": now.isoformat(),
            "level": 1,
            "tenant": alert.tenant,
        }
        if evaluation["previous_value"] is not None:
            payload["previous_value"] = evaluation["previous_value"]
        if evaluation["change_pct"] is not None:
            payload["change_pct"] = evaluation["change_pct"]
        await deliver(
            dispatcher,
            alert,
            payload,
            event_type="alert.triggered",
            current_value=evaluation["current_value"],
            previous_value=evaluation["previous_value"],
            change_pct=evaluation["change_pct"],
            webhook_url=alert.escalation[0].webhook_url,
        )
        alert.last_triggered_at = now
        alert.last_condition_triggered = True
        alert.updated_at = now
        return alert, True, 1

    if current_triggered and alert.fired_at is not None:
        next_step = next_escalation_step(alert, now)
        if next_step is not None:
            duration_minutes = max(0, int((now - alert.fired_at).total_seconds() // 60))
            payload = {
                "alert_id": alert.id,
                "alert_name": alert.name,
                "status": "sustained",
                "metric": alert.metric,
                "current_value": evaluation["current_value"],
                "threshold": alert.threshold,
                "condition": alert.condition,
                "window": alert.window,
                "triggered_at": alert.fired_at.isoformat(),
                "fired_at": alert.fired_at.isoformat(),
                "level": next_step.level,
                "duration_minutes": duration_minutes,
                "tenant": alert.tenant,
            }
            if evaluation["previous_value"] is not None:
                payload["previous_value"] = evaluation["previous_value"]
            if evaluation["change_pct"] is not None:
                payload["change_pct"] = evaluation["change_pct"]
            await deliver(
                dispatcher,
                alert,
                payload,
                event_type=(
                    "alert.escalated"
                    if next_step.level > alert.last_escalation_level
                    else "alert.sustained"
                ),
                current_value=evaluation["current_value"],
                previous_value=evaluation["previous_value"],
                change_pct=evaluation["change_pct"],
                webhook_url=next_step.webhook_url,
            )
            alert.last_triggered_at = now
            alert.last_escalation_level = max(
                alert.last_escalation_level,
                next_step.level,
            )
            alert.updated_at = now
            triggered += 1
            alert_changed = True
        alert.state = "sustained"
        alert.last_condition_triggered = True
        return alert, alert_changed, triggered

    if not current_triggered and alert.fired_at is not None:
        duration_minutes = max(0, int((now - alert.fired_at).total_seconds() // 60))
        payload = {
            "alert_id": alert.id,
            "alert_name": alert.name,
            "status": "resolved",
            "metric": alert.metric,
            "resolved_value": evaluation["current_value"],
            "fired_at": alert.fired_at.isoformat(),
            "resolved_at": now.isoformat(),
            "duration_minutes": duration_minutes,
            "tenant": alert.tenant,
        }
        notified_urls: list[str] = []
        for step in alert.escalation:
            if step.level > max(1, alert.last_escalation_level):
                continue
            if step.webhook_url not in notified_urls:
                notified_urls.append(step.webhook_url)
        for webhook_url in notified_urls or [alert.webhook_url]:
            await deliver(
                dispatcher,
                alert,
                payload,
                event_type="alert.resolved",
                current_value=evaluation["current_value"],
                previous_value=evaluation["previous_value"],
                change_pct=evaluation["change_pct"],
                webhook_url=webhook_url,
            )
            triggered += 1
        alert.state = "resolved"
        alert.resolved_at = now
        alert.fired_at = None
        alert.last_escalation_level = 0
        alert.last_triggered_at = now
        alert.last_condition_triggered = False
        alert.updated_at = now
        return alert, True, triggered

    if alert.state == "resolved":
        alert.state = "ok"
        alert.updated_at = now
        alert_changed = True
    alert.last_condition_triggered = False
    return alert, alert_changed, triggered


async def deliver(
    dispatcher: AlertDispatcher,
    alert: AlertRule,
    payload: dict,
    *,
    event_type: str,
    current_value: float | None = None,
    previous_value: float | None = None,
    change_pct: float | None = None,
    webhook_url: str | None = None,
) -> dict:
    from src.serving.api import alert_dispatcher as compat

    conn = dispatcher.app.state.query_engine._conn
    ensure_alert_history_table(conn)
    delivery_id = str(uuid.uuid4())
    body = _event_body(payload)
    headers = {
        "Content-Type": "application/json",
        "X-AgentFlow-Event": event_type,
        "X-AgentFlow-Signature": _signature(alert.secret, body),
        "X-AgentFlow-Delivery": delivery_id,
    }
    attempts = 0
    success = False
    status_code: int | None = None
    error: str | None = None

    async with compat.httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(1, 4):
            attempts = attempt
            error = None
            try:
                response = await client.post(
                    webhook_url or alert.webhook_url,
                    content=body,
                    headers=headers,
                )
                status_code = response.status_code
                success = 200 <= response.status_code < 300
                if response.status_code < 500:
                    break
            except (compat.httpx.TimeoutException, compat.httpx.TransportError) as exc:
                status_code = None
                success = False
                error = str(exc)

            if attempt < 3:
                delay = dispatcher.backoff_seconds[
                    min(attempt - 1, len(dispatcher.backoff_seconds) - 1)
                ]
                await asyncio.sleep(delay)

    log_alert_history(
        conn,
        delivery_id=delivery_id,
        alert=alert,
        metric=alert.metric,
        current_value=current_value,
        previous_value=previous_value,
        change_pct=change_pct,
        threshold=alert.threshold,
        condition=alert.condition,
        window=alert.window,
        event_type=event_type,
        status_code=status_code,
        success=success,
        error=error,
        payload=payload,
    )
    return {
        "delivery_id": delivery_id,
        "alert_id": alert.id,
        "event_type": event_type,
        "success": success,
        "status_code": status_code,
        "error": error,
        "attempts": attempts,
    }
