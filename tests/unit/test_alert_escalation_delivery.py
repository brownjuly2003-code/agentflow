"""Alert state advances only on successful delivery (no Docker).

evaluate_rule and deliver are monkeypatched so the escalation state machine can
be driven without a live DuckDB/metric/HTTP stack. Covers audit_28_06_26.md #4:
a failed page must NOT record the alert as fired/escalated (which would go silent
until cooldown) — the next evaluation tick re-attempts instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.serving.api.alerts.escalation as escalation
from src.serving.api.alerts.dispatcher import (
    AlertEscalationStep,
    AlertRule,
    next_escalation_step,
)

_NOW = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)


def _alert(**overrides: object) -> AlertRule:
    defaults: dict[str, object] = {
        "id": "a1",
        "name": "High error rate",
        "tenant": "acme",
        "metric": "error_rate",
        "window": "1h",
        "condition": "above",
        "threshold": 0.1,
        "webhook_url": "https://hooks.example.com/x",
        "secret": "s",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return AlertRule(**defaults)


def _patch_eval(monkeypatch: pytest.MonkeyPatch, *, triggered: bool) -> None:
    monkeypatch.setattr(
        escalation,
        "evaluate_rule",
        lambda dispatcher, alert, now: {
            "triggered": triggered,
            "current_value": 0.5,
            "previous_value": None,
            "change_pct": None,
        },
    )


def _patch_deliver(monkeypatch: pytest.MonkeyPatch, *, success: bool) -> None:
    async def _deliver(*args: object, **kwargs: object) -> dict[str, object]:
        return {"success": success, "error": None if success else "timeout"}

    monkeypatch.setattr(escalation, "deliver", _deliver)


@pytest.mark.asyncio
async def test_fire_advances_state_on_delivery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_eval(monkeypatch, triggered=True)
    _patch_deliver(monkeypatch, success=True)

    alert, changed, triggered = await escalation.dispatch_alert(None, _alert(), _NOW)

    assert alert.fired_at == _NOW
    assert alert.state == "firing"
    assert alert.last_escalation_level == 1
    assert triggered == 1


@pytest.mark.asyncio
async def test_fire_does_not_advance_state_on_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_eval(monkeypatch, triggered=True)
    _patch_deliver(monkeypatch, success=False)

    alert, changed, triggered = await escalation.dispatch_alert(None, _alert(), _NOW)

    # fired_at stays None so the next evaluation tick re-attempts the page rather
    # than going silent until cooldown.
    assert alert.fired_at is None
    assert alert.state != "firing"
    assert triggered == 0


@pytest.mark.asyncio
async def test_escalation_level_not_advanced_on_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_eval(monkeypatch, triggered=True)
    _patch_deliver(monkeypatch, success=False)

    fired = datetime(2026, 6, 28, 11, 0, tzinfo=UTC)  # 60 min before _NOW
    alert = _alert(
        escalation=[
            AlertEscalationStep(level=2, after_minutes=10, webhook_url="https://h.example.com/l2")
        ],
        fired_at=fired,
        state="firing",
        last_escalation_level=1,
        last_condition_triggered=True,
    )

    result, changed, triggered = await escalation.dispatch_alert(None, alert, _NOW)

    assert result.last_escalation_level == 1  # not advanced to 2 on failed delivery
    assert triggered == 0


# --- next_escalation_step: no intermediate-level skip (audit_28_06_26.md §5 medium) ---

_FIRED = datetime(2026, 6, 28, 11, 0, tzinfo=UTC)  # 60 min before _NOW


def _three_level_alert(last_level: int) -> AlertRule:
    return _alert(
        escalation=[
            AlertEscalationStep(level=1, after_minutes=0, webhook_url="https://h/l1"),
            AlertEscalationStep(level=2, after_minutes=10, webhook_url="https://h/l2"),
            AlertEscalationStep(level=3, after_minutes=20, webhook_url="https://h/l3"),
        ],
        fired_at=_FIRED,
        state="firing",
        last_escalation_level=last_level,
    )


def test_next_escalation_step_advances_one_level_at_a_time() -> None:
    # All three levels are due at _NOW (60 min elapsed >= 0/10/20), but a single
    # tick must page the *next* level (2), not jump to the highest (3) and skip
    # level 2's on-call recipient.
    step = next_escalation_step(_three_level_alert(last_level=1), _NOW)
    assert step is not None
    assert step.level == 2
    assert step.webhook_url == "https://h/l2"

    # After level 2 is recorded, the following tick advances to level 3.
    step = next_escalation_step(_three_level_alert(last_level=2), _NOW)
    assert step is not None
    assert step.level == 3

    # Once the top level is reached there is nothing further to escalate to.
    assert next_escalation_step(_three_level_alert(last_level=3), _NOW) is None


def test_next_escalation_step_picks_lowest_due_regardless_of_list_order() -> None:
    # Robust to an escalation list that is not sorted by level.
    alert = _alert(
        escalation=[
            AlertEscalationStep(level=3, after_minutes=20, webhook_url="https://h/l3"),
            AlertEscalationStep(level=2, after_minutes=10, webhook_url="https://h/l2"),
        ],
        fired_at=_FIRED,
        state="firing",
        last_escalation_level=1,
    )
    step = next_escalation_step(alert, _NOW)
    assert step is not None
    assert step.level == 2
