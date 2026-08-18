"""Contract tests for the tracked soak observer abort policy.

Grounded in docs/perf/golden-4h-soak-failures-01-05-rca-2026-08-09.md:

- ``-01``/``-02``: two Kubernetes API observation failures must not become a
  pod-topology abort while Flink is RUNNING.
- ``-05``: a terminal Flink job state must win immediately; the later
  TaskManager-gone ``1/1`` topology samples are downstream symptoms and must
  not be stored as the first abort reason.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "soak_observer_policy.py"


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing observer policy at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "soak_observer_policy_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass string-annotation resolution requires the module to be
    # importable through sys.modules while exec_module runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _policy(module, **overrides):
    defaults = {
        "expected_pods": 2,
        "max_pod_restarts": 1,
        "api_streak_need": 5,
        "flink_streak_need": 5,
        "topology_streak_need": 2,
    }
    defaults.update(overrides)
    return module.FlinkPodsAbortPolicy(**defaults)


def _flink(module, *, ok=True, job_state="RUNNING", tasks_running=2, tasks_total=2, error=None):
    return module.FlinkSample(
        ok=ok,
        job_state=job_state,
        tasks_running=tasks_running,
        tasks_total=tasks_total,
        tasks_all_running=(tasks_total > 0 and tasks_running == tasks_total),
        error=error,
    )


def _pods(
    module,
    *,
    ok=True,
    api_error=None,
    ready_count=2,
    total_count=2,
    all_running_ready=True,
    restart_total=0,
):
    return module.PodsSample(
        ok=ok,
        api_error=api_error,
        ready_count=ready_count,
        total_count=total_count,
        all_running_ready=all_running_ready,
        restart_total=restart_total,
    )


def test_terminal_flink_state_aborts_immediately():
    module = _load_module()
    policy = _policy(module)

    decision = policy.observe(
        _flink(module, job_state="FAILED", tasks_running=0, tasks_total=0),
        _pods(module),
    )

    assert decision is not None
    assert decision.reason_class == "flink_terminal"
    assert "FAILED" in decision.detail


def test_soak05_chronology_yields_flink_terminal_not_pod_topology():
    module = _load_module()
    policy = _policy(module)

    # Sample 244: RUNNING 2/2 with a transient pod-list TimeoutError.
    assert (
        policy.observe(
            _flink(module),
            _pods(module, ok=False, api_error="TimeoutError"),
        )
        is None
    )
    # Sample 245: Flink REST HTTPError; pods still 2/2.
    assert (
        policy.observe(
            _flink(
                module, ok=False, job_state=None, tasks_running=0, tasks_total=0, error="HTTPError"
            ),
            _pods(module),
        )
        is None
    )
    # Sample 246: Flink FAILED 0/0; pods still 2/2 -> decisive now.
    decision = policy.observe(
        _flink(module, job_state="FAILED", tasks_running=0, tasks_total=0),
        _pods(module),
    )
    assert decision is not None
    assert decision.reason_class == "flink_terminal"

    # Sample 247: TaskManager gone (1/1) must not rewrite the stored reason.
    later = policy.observe(
        _flink(module, job_state="FAILED", tasks_running=0, tasks_total=0),
        _pods(module, ready_count=1, total_count=1, all_running_ready=True),
    )
    assert later is decision


def test_two_api_observation_failures_do_not_abort_while_flink_running():
    module = _load_module()
    policy = _policy(module)

    for _ in range(2):
        decision = policy.observe(
            _flink(module),
            _pods(module, ok=False, api_error="TimeoutError"),
        )
    assert decision is None


def test_api_observation_streak_aborts_as_api_class_never_topology():
    module = _load_module()
    policy = _policy(module)

    decision = None
    for _ in range(5):
        decision = policy.observe(
            _flink(module),
            _pods(module, ok=False, api_error="URLError"),
        )
    assert decision is not None
    assert decision.reason_class == "pods_api_unhealthy"
    assert "URLError" in decision.detail


def test_real_topology_loss_aborts_with_flink_context():
    module = _load_module()
    policy = _policy(module)

    decision = None
    for _ in range(2):
        decision = policy.observe(
            _flink(module),
            _pods(module, ready_count=1, total_count=2, all_running_ready=False),
        )
    assert decision is not None
    assert decision.reason_class == "pod_topology_unhealthy"
    assert "RUNNING" in decision.detail


def test_flink_led_degradation_is_not_stored_as_pod_topology():
    module = _load_module()
    policy = _policy(module)

    # Flink degrades first (SUSPENDED, non-terminal), pods still fine.
    for _ in range(2):
        assert (
            policy.observe(
                _flink(module, job_state="SUSPENDED", tasks_running=0, tasks_total=0),
                _pods(module),
            )
            is None
        )
    # Topology follows two samples later; topology streak (2) fires first,
    # but the abort must be attributed to the older Flink degradation.
    policy.observe(
        _flink(module, job_state="SUSPENDED", tasks_running=0, tasks_total=0),
        _pods(module, ready_count=1, total_count=1, all_running_ready=True),
    )
    decision = policy.observe(
        _flink(module, job_state="SUSPENDED", tasks_running=0, tasks_total=0),
        _pods(module, ready_count=1, total_count=1, all_running_ready=True),
    )
    assert decision is not None
    assert decision.reason_class == "flink_led_topology_loss"
    assert "SUSPENDED" in decision.detail


def test_pod_restart_budget_aborts_when_exceeded():
    module = _load_module()
    policy = _policy(module)

    decision = policy.observe(
        _flink(module),
        _pods(module, restart_total=2),
    )
    assert decision is not None
    assert decision.reason_class == "pod_restart_budget"


def test_first_decision_is_frozen():
    module = _load_module()
    policy = _policy(module)

    first = policy.observe(
        _flink(module, job_state="FAILED", tasks_running=0, tasks_total=0),
        _pods(module),
    )
    second = policy.observe(
        _flink(module),
        _pods(module),
    )
    assert second is first
