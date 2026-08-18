"""Contract tests for host-persistent Flink failure evidence capture."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "capture_flink_failure_evidence.py"


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing collector at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "flink_failure_evidence_capture_under_test", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cr(
    *,
    state: str = "RUNNING",
    lifecycle: str = "STABLE",
    jobmanager: str = "READY",
) -> dict:
    return {
        "metadata": {
            "name": "agentflow-soak-rv-stream-processor",
            "uid": "cr-uid",
            "generation": 9,
        },
        "spec": {"inlineSecret": "DO_NOT_PERSIST"},
        "status": {
            "lifecycleState": lifecycle,
            "jobManagerDeploymentStatus": jobmanager,
            "jobStatus": {
                "jobId": "0123456789abcdef",
                "state": state,
            },
        },
    }


def _pods(*, ready: bool = True, restarts: int = 0) -> dict:
    state = {"running": {"startedAt": "2026-08-09T00:00:00Z"}}
    last_state = {}
    if restarts:
        last_state = {
            "terminated": {
                "exitCode": 137,
                "reason": "OOMKilled",
                "finishedAt": "2026-08-09T00:01:00Z",
            }
        }
    items = []
    for component in ("jobmanager", "taskmanager"):
        items.append(
            {
                "metadata": {
                    "name": f"flink-{component}-0",
                    "uid": f"{component}-uid",
                    "annotations": {"secret": "DO_NOT_PERSIST"},
                },
                "spec": {
                    "nodeName": "kind-control-plane",
                    "containers": [
                        {
                            "name": "flink-main-container",
                            "env": [{"value": "DO_NOT_PERSIST"}],
                        }
                    ],
                },
                "status": {
                    "phase": "Running" if ready else "Failed",
                    "containerStatuses": [
                        {
                            "name": "flink-main-container",
                            "ready": ready,
                            "restartCount": restarts,
                            "state": state if ready else last_state,
                            "lastState": last_state,
                        }
                    ],
                },
            }
        )
    return {"items": items}


def test_watcher_arms_only_on_healthy_snapshot_and_triggers_on_terminal_state():
    module = _load_module()

    assert module.is_healthy_snapshot(_cr(), _pods(), expected_pods=2)
    assert not module.is_healthy_snapshot(_cr(state="SUSPENDED"), _pods(), expected_pods=2)
    assert not module.is_healthy_snapshot(_cr(lifecycle="FAILED"), _pods(), expected_pods=2)
    assert not module.is_healthy_snapshot(_cr(jobmanager="MISSING"), _pods(), expected_pods=2)
    assert not module.is_healthy_snapshot(_cr(), _pods(ready=False), expected_pods=2)

    assert module.failure_reasons(
        _cr(state="FAILED"),
        _pods(),
        baseline_restarts=0,
        expected_pods=2,
    ) == ["flink_job_state=FAILED"]
    assert module.failure_reasons(
        _cr(),
        _pods(restarts=1),
        baseline_restarts=0,
        expected_pods=2,
    ) == ["pod_restarts=2 baseline=0"]


def test_failure_surface_classification_distinguishes_observation_flink_and_topology():
    module = _load_module()

    assert module.classify_failure_surfaces(
        [
            "flink_job_state=FAILED",
            "jobmanager_deployment_status=MISSING",
            "pod_total=1 expected=2",
        ],
        snapshot_errors=["watch_flink_pods: timeout"],
    ) == ["api_observation", "terminal_flink", "pod_topology"]


def test_capture_preserves_all_required_surfaces_without_specs_or_mutations(tmp_path):
    module = _load_module()
    events = {
        "items": [
            {
                "metadata": {
                    "name": "flink-warning.123",
                    "namespace": "agentflow",
                    "annotations": {"secret": "DO_NOT_PERSIST"},
                },
                "involvedObject": {
                    "kind": "Pod",
                    "name": "flink-taskmanager-0",
                    "uid": "taskmanager-uid",
                },
                "type": "Warning",
                "reason": "BackOff",
                "message": "container restarted",
                "lastTimestamp": "2026-08-09T00:02:00Z",
                "count": 1,
            }
        ]
    }
    observer_pods = {
        "items": [
            {
                "metadata": {"name": "observer-pod"},
                "status": {
                    "containerStatuses": [
                        {
                            "name": "observer",
                            "ready": True,
                            "restartCount": 0,
                            "state": {"running": {}},
                            "lastState": {},
                        }
                    ]
                },
            }
        ]
    }

    class FakeClient:
        def __init__(self):
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args: str):
            self.calls.append(args)
            if args[:2] == ("get", "events"):
                return module.CommandResult(0, json.dumps(events), "")
            if args[:2] == ("get", "--raw"):
                if "/jobs/overview" in args[2]:
                    body = {"jobs": [{"jid": "0123456789abcdef"}]}
                elif "/exceptions" in args[2]:
                    body = {"root-exception": "java.lang.IllegalStateException"}
                else:
                    body = {"status": "available"}
                return module.CommandResult(0, json.dumps(body), "")
            if args[:4] == (
                "get",
                "pods",
                "-l",
                "job-name=agentflow-soak-observer",
            ):
                return module.CommandResult(0, json.dumps(observer_pods), "")
            if args[0] == "logs":
                stream = "previous" if "--previous=true" in args else "current"
                return module.CommandResult(0, f"{stream} log\n", "")
            if args[0] == "exec":
                evidence_name = args[-1]
                payload = {
                    "/evidence/soak-observer.jsonl": '{"sample":1}\n',
                    "/evidence/soak-observer-latest.json": '{"sample":1}\n',
                    "/evidence/ABORT": "flink_unhealthy\n",
                }[evidence_name]
                return module.CommandResult(0, payload, "")
            raise AssertionError(f"unexpected command: {args}")

    client = FakeClient()
    config = module.CaptureConfig(
        context="kind-agentflow",
        namespace="agentflow",
        flink_deployment="agentflow-soak-rv-stream-processor",
        pod_selector="app=agentflow-soak-rv-stream-processor",
        flink_rest_service="agentflow-soak-rv-stream-processor-rest",
        flink_rest_port=8081,
        observer_job="agentflow-soak-observer",
        observer_container="observer",
        observer_evidence_dir="/evidence",
        output_dir=tmp_path,
        log_since="6h",
    )

    result = module.capture_evidence(
        client,
        config,
        trigger_reasons=["flink_job_state=FAILED"],
        cr=_cr(state="FAILED"),
        pods=_pods(restarts=1),
        captured_at=datetime(2026, 8, 9, 0, 3, tzinfo=UTC),
    )

    bundle = result.bundle_dir
    required = {
        "flinkdeployment-status.json",
        "pod-termination-states.json",
        "namespace-events.json",
        "flink/jobs-overview.json",
        "flink/job-exceptions.json",
        "flink/job-execution-result.json",
        "flink/job-checkpoints.json",
        "logs/flink-jobmanager-0__flink-main-container.current.log",
        "logs/flink-jobmanager-0__flink-main-container.previous.log",
        "observer/soak-observer.jsonl",
        "observer/soak-observer-latest.json",
        "observer/ABORT",
        "observer/observer.current.log",
        "observer/observer.previous.log",
        "manifest.json",
    }
    assert required <= {
        path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()
    }

    persisted_status = (bundle / "flinkdeployment-status.json").read_text(encoding="utf-8")
    persisted_pods = (bundle / "pod-termination-states.json").read_text(encoding="utf-8")
    persisted_events = (bundle / "namespace-events.json").read_text(encoding="utf-8")
    assert "DO_NOT_PERSIST" not in persisted_status
    assert "DO_NOT_PERSIST" not in persisted_pods
    assert "DO_NOT_PERSIST" not in persisted_events
    assert "OOMKilled" in persisted_pods
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["failure_surfaces"] == ["terminal_flink"]

    assert any(call[0] == "logs" and "--previous=true" in call for call in client.calls)
    first_flink_log = next(
        index
        for index, call in enumerate(client.calls)
        if call[0] == "logs" and call[1].startswith("flink-")
    )
    first_secondary_capture = next(
        index
        for index, call in enumerate(client.calls)
        if call[:2] in {("get", "events"), ("get", "--raw")}
    )
    assert first_flink_log < first_secondary_capture
    assert {call[0] for call in client.calls} <= {"exec", "get", "logs"}
    assert not result.errors

    if os.name != "nt":
        assert stat.S_IMODE(bundle.stat().st_mode) == 0o700
        for path in bundle.rglob("*"):
            if path.is_file():
                assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_capture_records_unavailable_previous_log_without_losing_manifest(tmp_path):
    module = _load_module()

    class PartialClient:
        def run(self, *args: str):
            if args[:2] == ("get", "events"):
                return module.CommandResult(0, '{"items":[]}', "")
            if args[:2] == ("get", "--raw"):
                return module.CommandResult(0, '{"jobs":[]}', "")
            if args[:2] == ("get", "pods"):
                return module.CommandResult(0, '{"items":[]}', "")
            if args[0] == "logs" and "--previous=true" in args:
                return module.CommandResult(1, "", "previous terminated container not found")
            if args[0] == "logs":
                return module.CommandResult(0, "current log\n", "")
            raise AssertionError(f"unexpected command: {args}")

    config = module.CaptureConfig(
        context="kind-agentflow",
        namespace="agentflow",
        flink_deployment="flink",
        pod_selector="app=flink",
        flink_rest_service="flink-rest",
        flink_rest_port=8081,
        observer_job="observer",
        observer_container="observer",
        observer_evidence_dir="/evidence",
        output_dir=tmp_path,
        log_since="6h",
    )

    result = module.capture_evidence(
        PartialClient(),
        config,
        trigger_reasons=["pod_ready=1/2"],
        cr=_cr(),
        pods={"items": [_pods()["items"][0]]},
        captured_at=datetime(2026, 8, 9, 0, 4, tzinfo=UTC),
    )

    assert (result.bundle_dir / "manifest.json").is_file()
    error_path = (
        result.bundle_dir / "logs" / "flink-jobmanager-0__flink-main-container.previous.error.txt"
    )
    assert error_path.read_text(encoding="utf-8").strip() == (
        "previous terminated container not found"
    )
    assert any("previous" in error for error in result.errors)


def test_capture_marks_missing_flink_pods_incomplete(tmp_path):
    module = _load_module()
    observer_source = tmp_path / "observer-source"
    observer_source.mkdir()
    for name in module.OBSERVER_EVIDENCE_FILES:
        (observer_source / name).write_text("{}\n", encoding="utf-8")

    class NoPodsClient:
        def run(self, *args: str):
            if args[:2] == ("get", "events"):
                return module.CommandResult(0, '{"items":[]}', "")
            if args[:2] == ("get", "--raw"):
                if "/jobs/overview" in args[2]:
                    return module.CommandResult(0, '{"jobs":[{"jid":"0123456789abcdef"}]}', "")
                return module.CommandResult(0, "{}", "")
            raise AssertionError(f"unexpected command: {args}")

    config = module.CaptureConfig(
        context="kind-agentflow",
        namespace="agentflow",
        flink_deployment="flink",
        pod_selector="app=flink",
        flink_rest_service="flink-rest",
        flink_rest_port=8081,
        observer_job="observer",
        observer_container="observer",
        observer_evidence_dir="/evidence",
        output_dir=tmp_path / "bundles",
        log_since="6h",
        observer_local_dir=observer_source,
        expected_pods=2,
    )

    result = module.capture_evidence(
        NoPodsClient(),
        config,
        trigger_reasons=["pod_total=0 expected=2"],
        cr=_cr(state="FAILED", lifecycle="FAILED", jobmanager="MISSING"),
        pods={"items": []},
        captured_at=datetime(2026, 8, 9, 0, 5, tzinfo=UTC),
    )

    manifest = json.loads((result.bundle_dir / "manifest.json").read_text("utf-8"))
    assert not manifest["complete"]
    assert "flink_logs: pod_total=0 expected=2" in result.errors
    assert (result.bundle_dir / "logs" / "pod-count.error.txt").is_file()


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class _UnusedClient:
    def run(self, *args: str):
        raise AssertionError(f"kubectl should not run during watch unit tests: {args}")


def _watch_config(module, tmp_path: Path):
    return module.CaptureConfig(
        context="kind-agentflow",
        namespace="agentflow",
        flink_deployment="flink",
        pod_selector="app=flink",
        flink_rest_service="flink-rest",
        flink_rest_port=8081,
        observer_job="observer",
        observer_container="observer",
        observer_evidence_dir="/evidence",
        output_dir=tmp_path,
        log_since="6h",
    )


def _install_clock(module, monkeypatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)
    return clock


def _queue_snapshots(module, monkeypatch, snapshots, *, stop_file: Path | None = None):
    remaining = list(snapshots)

    def fake_snapshot(client, config):
        if not remaining:
            raise AssertionError("watch requested more snapshots than queued")
        snapshot = remaining.pop(0)
        if stop_file is not None and not remaining:
            stop_file.write_text("stop\n", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(module, "_snapshot", fake_snapshot)


def _stub_capture(module, monkeypatch, tmp_path: Path) -> dict:
    calls: dict = {"count": 0, "reasons": None}

    def fake_capture(client, config, *, trigger_reasons, cr=None, pods=None, captured_at=None):
        calls["count"] += 1
        calls["reasons"] = list(trigger_reasons)
        bundle = tmp_path / "stub-bundle"
        bundle.mkdir(exist_ok=True)
        return module.CaptureResult(bundle, ())

    monkeypatch.setattr(module, "capture_evidence", fake_capture)
    return calls


def _chronology(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_transitional_state_recovering_within_grace_does_not_capture(tmp_path, monkeypatch):
    module = _load_module()
    clock = _install_clock(module, monkeypatch)
    sleeps = {"n": 0}

    def sleep_then_stop(seconds: float) -> None:
        clock.sleep(seconds)
        sleeps["n"] += 1
        # arm + transitional + recovered; leave the last state file as armed
        if sleeps["n"] >= 3:
            raise RuntimeError("stop-after-recovery")

    def ban_capture(*_args, **_kwargs):
        raise AssertionError("capture_evidence must not run for a recovered HA blip")

    monkeypatch.setattr(module.time, "sleep", sleep_then_stop)
    monkeypatch.setattr(module, "capture_evidence", ban_capture)
    _queue_snapshots(
        module,
        monkeypatch,
        [
            (_cr(), _pods(), []),
            (_cr(state="SUSPENDED"), _pods(), []),
            (_cr(), _pods(), []),
        ],
    )

    with pytest.raises(RuntimeError, match="stop-after-recovery"):
        module.watch(
            _UnusedClient(),
            _watch_config(module, tmp_path),
            poll_interval_seconds=1.0,
            timeout_seconds=0,
            stop_file=None,
            transitional_grace_seconds=90.0,
        )

    bundle_dirs = [
        path for path in tmp_path.iterdir() if path.is_dir() and path.name.startswith("failure-")
    ]
    assert bundle_dirs == []
    state = json.loads((tmp_path / "failure-watcher-state.json").read_text(encoding="utf-8"))
    assert state["state"] == "armed"
    recovered = [
        entry
        for entry in _chronology(tmp_path / "failure-watcher-chronology.jsonl")
        if entry.get("state") == "transient_recovered"
    ]
    assert len(recovered) == 1
    assert "flink_job_state=SUSPENDED" in recovered[0]["recovered_reasons"]


def test_transitional_state_persisting_past_grace_captures(tmp_path, monkeypatch):
    module = _load_module()
    _install_clock(module, monkeypatch)
    calls = _stub_capture(module, monkeypatch, tmp_path)
    _queue_snapshots(
        module,
        monkeypatch,
        [
            (_cr(), _pods(), []),
            (_cr(state="SUSPENDED"), _pods(), []),
            (_cr(state="SUSPENDED"), _pods(), []),
        ],
    )

    rc = module.watch(
        _UnusedClient(),
        _watch_config(module, tmp_path),
        poll_interval_seconds=90.0,
        timeout_seconds=0,
        stop_file=None,
        transitional_grace_seconds=90.0,
    )

    assert rc == 2
    assert calls["count"] == 1
    assert any(reason.startswith("transitional_persisted=") for reason in calls["reasons"])
    assert "flink_job_state=SUSPENDED" in calls["reasons"]


def test_immediate_terminal_state_still_captures_on_first_sample(tmp_path, monkeypatch):
    module = _load_module()
    _install_clock(module, monkeypatch)
    calls = _stub_capture(module, monkeypatch, tmp_path)
    _queue_snapshots(
        module,
        monkeypatch,
        [
            (_cr(), _pods(), []),
            (_cr(state="FAILED"), _pods(), []),
        ],
    )

    rc = module.watch(
        _UnusedClient(),
        _watch_config(module, tmp_path),
        poll_interval_seconds=1.0,
        timeout_seconds=0,
        stop_file=None,
        transitional_grace_seconds=90.0,
    )

    assert rc == 2
    assert calls["count"] == 1
    assert calls["reasons"] == ["flink_job_state=FAILED"]


def test_grace_zero_restores_legacy_behaviour(tmp_path, monkeypatch):
    module = _load_module()
    _install_clock(module, monkeypatch)
    calls = _stub_capture(module, monkeypatch, tmp_path)
    _queue_snapshots(
        module,
        monkeypatch,
        [
            (_cr(), _pods(), []),
            (_cr(state="SUSPENDED"), _pods(), []),
        ],
    )

    rc = module.watch(
        _UnusedClient(),
        _watch_config(module, tmp_path),
        poll_interval_seconds=1.0,
        timeout_seconds=0,
        stop_file=None,
        transitional_grace_seconds=0,
    )

    assert rc == 2
    assert calls["count"] == 1
    assert calls["reasons"] == ["flink_job_state=SUSPENDED"]


def test_pod_restart_delta_is_immediate_even_during_transition(tmp_path, monkeypatch):
    module = _load_module()
    _install_clock(module, monkeypatch)
    calls = _stub_capture(module, monkeypatch, tmp_path)
    _queue_snapshots(
        module,
        monkeypatch,
        [
            (_cr(), _pods(), []),
            (_cr(state="SUSPENDED"), _pods(restarts=1), []),
        ],
    )

    rc = module.watch(
        _UnusedClient(),
        _watch_config(module, tmp_path),
        poll_interval_seconds=1.0,
        timeout_seconds=0,
        stop_file=None,
        transitional_grace_seconds=90.0,
    )

    assert rc == 2
    assert calls["count"] == 1
    assert "flink_job_state=SUSPENDED" in calls["reasons"]
    assert "pod_restarts=2 baseline=0" in calls["reasons"]
    assert not any(reason.startswith("transitional_persisted=") for reason in calls["reasons"])
