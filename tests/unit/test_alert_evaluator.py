"""evaluate_rule change_pct semantics from a zero baseline (audit_28_06_26.md §5).

A change from a zero baseline is an undefined (unbounded) ratio. It must fire by
direction — any rise satisfies an "above" rule, any fall a "below" rule — instead
of reporting a flat 100% sentinel that silently under-reported spikes from zero.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.serving.api.alerts.evaluator as evaluator
from src.serving.api.alerts.dispatcher import AlertRule

_NOW = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)


def _change_alert(threshold: float) -> AlertRule:
    return AlertRule(
        id="a1",
        name="Change rule",
        tenant="acme",
        metric="revenue",
        window="1h",
        condition="change_pct",
        threshold=threshold,
        webhook_url="https://hooks.example.com/x",
        secret="s",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _patch_metrics(monkeypatch: pytest.MonkeyPatch, *, current: float, previous: float) -> None:
    def _fake(dispatcher, metric_name, window, tenant_id, *, as_of=None):  # type: ignore[no-untyped-def]
        # as_of is set only for the *previous* window lookup.
        return {"value": previous if as_of is not None else current, "unit": "USD"}

    monkeypatch.setattr(evaluator, "get_metric", _fake)


def test_rise_from_zero_fires_above_rule_even_past_100pct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Old behaviour reported a flat 100%, so an "above" rule with threshold > 100
    # never fired on a spike from zero. Now any rise fires it.
    _patch_metrics(monkeypatch, current=500.0, previous=0.0)
    result = evaluator.evaluate_rule(None, _change_alert(threshold=200.0), _NOW)
    assert result["triggered"] is True
    assert result["change_pct"] is None  # undefined ratio, not a misleading number


def test_no_change_from_zero_does_not_fire_above_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_metrics(monkeypatch, current=0.0, previous=0.0)
    result = evaluator.evaluate_rule(None, _change_alert(threshold=10.0), _NOW)
    assert result["triggered"] is False
    assert result["change_pct"] == 0.0


def test_fall_from_zero_fires_below_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    # current < 0 with a negative ("below") threshold = an unbounded drop.
    _patch_metrics(monkeypatch, current=-5.0, previous=0.0)
    result = evaluator.evaluate_rule(None, _change_alert(threshold=-10.0), _NOW)
    assert result["triggered"] is True
    assert result["change_pct"] is None


def test_nonzero_baseline_path_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression guard: the normal (non-zero baseline) path still computes a pct.
    _patch_metrics(monkeypatch, current=80.0, previous=100.0)
    result = evaluator.evaluate_rule(None, _change_alert(threshold=-10.0), _NOW)
    assert result["triggered"] is True  # -20% <= -10%
    assert result["change_pct"] == -20.0
