from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .dispatcher import AlertDispatcher, AlertRule


def evaluate_rule(
    dispatcher: AlertDispatcher,
    alert: AlertRule,
    now: datetime,
) -> dict[str, float | bool | None]:
    current_metric = get_metric(dispatcher, alert.metric, alert.window, alert.tenant)
    current_value = float(current_metric["value"])
    previous_value: float | None = None
    change_pct: float | None = None

    if alert.condition == "above":
        triggered = current_value > alert.threshold
    elif alert.condition == "below":
        triggered = current_value < alert.threshold
    else:
        previous_metric = get_metric(
            dispatcher,
            alert.metric,
            alert.window,
            alert.tenant,
            as_of=now - window_to_timedelta(alert.window),
        )
        previous_value = float(previous_metric["value"])
        if previous_value == 0:
            change_pct = 0.0 if current_value == 0 else 100.0
        else:
            change_pct = ((current_value - previous_value) / abs(previous_value)) * 100.0
        triggered = change_pct >= alert.threshold if alert.threshold >= 0 else change_pct <= alert.threshold

    return {
        "triggered": triggered,
        "current_value": round(current_value, 4),
        "previous_value": round(previous_value, 4) if previous_value is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
    }


def get_metric(
    dispatcher: AlertDispatcher,
    metric_name: str,
    window: str,
    tenant_id: str,
    *,
    as_of: datetime | None = None,
) -> dict:
    engine = dispatcher.app.state.query_engine
    try:
        return cast(
            dict,
            engine.get_metric(
                metric_name,
                window=window,
                as_of=as_of,
                tenant_id=tenant_id,
            ),
        )
    except TypeError as exc:
        if "tenant_id" not in str(exc):
            raise
        return cast(dict, engine.get_metric(metric_name, window=window, as_of=as_of))


def window_to_timedelta(window: str) -> timedelta:
    if window == "now":
        return timedelta(minutes=30)
    if window.endswith("m"):
        return timedelta(minutes=int(window[:-1]))
    if window.endswith("h"):
        return timedelta(hours=int(window[:-1]))
    raise ValueError(f"Unsupported alert window '{window}'")
