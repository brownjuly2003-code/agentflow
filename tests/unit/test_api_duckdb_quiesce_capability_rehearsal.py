"""Focused unit tests for the API DuckDB non-target scratch rehearsal harness.

All subprocess/SSH behavior is faked. No live remote command may run.
"""

# ruff: noqa: S108

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "rehearse_api_duckdb_quiesce_capabilities.py"

RUN_ID = "cap-rehearsal-20260811-01"
SAFE_SCRATCH_ROOT = f"/tmp/agentflow-api-duckdb-capability-rehearsal/{RUN_ID}"
ACK = "NON_TARGET_SCRATCH_REHEARSAL_ONLY"
DEFAULT_HOST = "deproject-mac"
EXECUTED_STATUS = "NON_TARGET_SCRATCH_REHEARSAL_EXECUTED"

PLANNED_CHECKS = (
    "timing/monotonic bounds",
    "scratch pause/resume behavior",
    "independent watchdog arm/fire/cancel behavior",
    "descriptor visibility on an exact scratch mount/path",
    "metadata tool/ACL/xattr capability",
    "same-directory atomic rename",
    "file and directory sync behavior",
)

FORBIDDEN_PAYLOAD_TOKENS = (
    "kubectl",
    "systemctl stop kubelet",
    "systemctl start kubelet",
    "systemctl restart kubelet",
    ".duckdb",
    "/var/lib/kubelet/pods/",
    "volumes/kubernetes.io~empty-dir/data",
    "c9d26829-c57f-4550-a86f-cdcc41e719fd",
    "agentflow-chk-restore-rv-api-20260802-01-59489dd45c-kk8tf",
    "8ed4b970504b8b702be7e01325a663bc7b3d91b3e8733c5c7fdb3bf6cf2e83bd",
)


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing harness at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "rehearse_api_duckdb_quiesce_capabilities_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _executed_remote_payload(*, statuses: dict[str, str] | None = None) -> dict[str, Any]:
    capability_checks = statuses or dict.fromkeys(PLANNED_CHECKS, "PASS")
    return {
        "status": EXECUTED_STATUS,
        "execute": True,
        "capability_checks": capability_checks,
        "check_evidence": {
            name: {"scope": "non-target scratch only", "observed": True} for name in PLANNED_CHECKS
        },
        "branch_eligibility": {
            "PAUSED_TASK": "ineligible",
            "KUBELET_GAP": "ineligible",
        },
    }


def test_plan_mode_performs_no_subprocess_and_emits_claim_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    spy = MagicMock(side_effect=AssertionError("subprocess.run must not be called"))
    monkeypatch.setattr(subprocess, "run", spy)

    code = module.main([])
    assert code == 0
    assert spy.call_count == 0

    result = module.build_plan_result(ssh_host=DEFAULT_HOST)
    assert result["status"] == "REHEARSAL_SETUP_READY_NOT_EXECUTED"
    assert result["execute"] is False
    assert result["ssh_host"] == DEFAULT_HOST
    assert result["planned_checks"] == list(PLANNED_CHECKS)
    claim = result["claim_boundary"]
    assert claim["authoritative_status"] == "CAPABILITY_REHEARSAL_REQUIRED"
    assert claim["preservation_status"] == "PRESERVATION_PARTIAL"
    assert claim["paused_task_eligible"] is False
    assert claim["kubelet_gap_eligible"] is False
    assert claim["i04_proved"] is False
    assert claim["i05_proved"] is False
    assert claim["i09_proved"] is False
    assert claim["runbook_approved"] is False
    assert claim["production_status_improved"] is False


def test_execute_requires_exact_acknowledgement_pairing() -> None:
    module = _load_module()

    code = module.main(
        [
            "--execute",
            "--run-id",
            RUN_ID,
            "--scratch-root",
            SAFE_SCRATCH_ROOT,
        ]
    )
    assert code == 2

    code = module.main(
        [
            "--execute",
            "--acknowledge",
            "WRONG_TOKEN",
            "--run-id",
            RUN_ID,
            "--scratch-root",
            SAFE_SCRATCH_ROOT,
        ]
    )
    assert code == 2

    code = module.main(["--acknowledge", ACK])
    assert code == 2


def test_safe_unique_scratch_path_accepted() -> None:
    module = _load_module()
    assert module.validate_run_id(RUN_ID) == RUN_ID
    assert module.validate_scratch_root(SAFE_SCRATCH_ROOT, RUN_ID) == SAFE_SCRATCH_ROOT


@pytest.mark.parametrize(
    ("path", "run_id"),
    [
        ("", RUN_ID),
        ("relative/path", RUN_ID),
        ("/", RUN_ID),
        ("/tmp/agentflow-api-duckdb-capability-rehearsal", RUN_ID),
        ("/tmp/agentflow-api-duckdb-capability-rehearsal/", RUN_ID),
        (f"/tmp/agentflow-api-duckdb-capability-rehearsal/{RUN_ID}/..", RUN_ID),
        (
            f"/tmp/other/../agentflow-api-duckdb-capability-rehearsal/{RUN_ID}",
            RUN_ID,
        ),
        (f"/tmp/agentflow-api-duckdb-capability-rehearsal/./{RUN_ID}", RUN_ID),
        (f"/tmp/agentflow-api-duckdb-capability-rehearsal//{RUN_ID}", RUN_ID),
        (
            "/var/lib/kubelet/pods/c9d26829-c57f-4550-a86f-cdcc41e719fd/"
            "volumes/kubernetes.io~empty-dir/data",
            RUN_ID,
        ),
        ("/tmp/other-prefix/cap-rehearsal-20260811-01", RUN_ID),
        (f"/tmp/agentflow-api-duckdb-capability-rehearsal/{RUN_ID}-extra", RUN_ID),
        ("/tmp/agentflow-api-duckdb-capability-rehearsal/other-id", RUN_ID),
    ],
)
def test_unsafe_scratch_paths_rejected_before_subprocess(
    path: str,
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    spy = MagicMock(side_effect=AssertionError("subprocess must not run for unsafe path"))
    monkeypatch.setattr(module.subprocess, "run", spy)

    with pytest.raises(ValueError):
        module.validate_scratch_root(path, run_id)

    code = module.main(
        [
            "--execute",
            "--acknowledge",
            ACK,
            "--run-id",
            run_id,
            "--scratch-root",
            path,
        ]
    )
    assert code == 1
    assert spy.call_count == 0


def test_ssh_argv_uses_shell_false_and_distinct_untrusted_entries() -> None:
    module = _load_module()
    host = "deproject-mac"
    argv = module.build_ssh_argv(
        host=host,
        run_id=RUN_ID,
        scratch_root=SAFE_SCRATCH_ROOT,
    )
    assert argv[0] == "ssh"
    assert host in argv
    assert RUN_ID in argv
    assert SAFE_SCRATCH_ROOT in argv
    assert argv.index(RUN_ID) > argv.index(host)
    assert argv.index(SAFE_SCRATCH_ROOT) > argv.index(RUN_ID)
    # Untrusted values must be discrete argv entries, not shell-interpolated.
    assert argv.count(host) == 1
    assert argv.count(RUN_ID) == 1
    assert argv.count(SAFE_SCRATCH_ROOT) == 1
    assert argv[argv.index(host)] == host
    assert argv[argv.index(RUN_ID)] == RUN_ID
    assert argv[argv.index(SAFE_SCRATCH_ROOT)] == SAFE_SCRATCH_ROOT
    assert "bash" in argv
    assert "-s" in argv


def test_strict_json_rejects_duplicates_malformed_and_schema_mismatch() -> None:
    module = _load_module()

    with pytest.raises(module.RehearsalError, match="duplicate"):
        module.parse_remote_json('{"status":"x","status":"y"}')

    with pytest.raises(module.RehearsalError, match="malformed"):
        module.parse_remote_json("{not-json")

    with pytest.raises(module.RehearsalError, match="schema"):
        module.parse_remote_json('{"status":"OK"}')

    with pytest.raises(module.RehearsalError, match="schema"):
        module.parse_remote_json("[]")


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "CAPTURE_ONLY_PASS"},
        {"execute": False},
        {"capability_checks": dict.fromkeys(PLANNED_CHECKS, "NOT_RUN")},
        {
            "branch_eligibility": {
                "PAUSED_TASK": "eligible",
                "KUBELET_GAP": "ineligible",
            }
        },
    ],
)
def test_remote_json_rejects_claim_boundary_upgrades(
    overrides: dict[str, Any],
) -> None:
    module = _load_module()
    payload = _executed_remote_payload()
    payload.update(overrides)

    with pytest.raises(module.RehearsalError, match="schema"):
        module.parse_remote_json(json.dumps(payload))


def test_nonzero_and_timeout_are_blocked_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    calls: list[Any] = []

    def failing_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args[0] if args else [],
            returncode=7,
            stdout="",
            stderr="remote failed",
        )

    with pytest.raises(module.RehearsalError, match="BLOCKED|failed|nonzero"):
        module.execute_rehearsal_setup(
            ssh_host=DEFAULT_HOST,
            run_id=RUN_ID,
            scratch_root=SAFE_SCRATCH_ROOT,
            runner=failing_runner,
        )
    assert len(calls) == 1

    def timeout_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "ssh", timeout=1)

    with pytest.raises(module.RehearsalError, match="timeout|BLOCKED|timed out"):
        module.execute_rehearsal_setup(
            ssh_host=DEFAULT_HOST,
            run_id=RUN_ID,
            scratch_root=SAFE_SCRATCH_ROOT,
            runner=timeout_runner,
        )
    assert len(calls) == 2

    # shell=False is mandatory when a real runner is used.
    captured: dict[str, Any] = {}

    def capture_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        payload = _executed_remote_payload()
        return subprocess.CompletedProcess(
            args=args[0] if args else [],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", capture_runner)
    result = module.execute_rehearsal_setup(
        ssh_host=DEFAULT_HOST,
        run_id=RUN_ID,
        scratch_root=SAFE_SCRATCH_ROOT,
    )
    assert captured["kwargs"].get("shell") is False
    assert result["execute"] is True
    assert result["status"] == EXECUTED_STATUS
    assert result["check_evidence"] == _executed_remote_payload()["check_evidence"]


def test_remote_json_accepts_all_bounded_statuses_with_exact_evidence() -> None:
    module = _load_module()
    statuses = {
        name: ("PASS", "PARTIAL", "BLOCKED")[index % 3] for index, name in enumerate(PLANNED_CHECKS)
    }
    payload = _executed_remote_payload(statuses=statuses)

    parsed = module.parse_remote_json(json.dumps(payload))

    assert parsed == payload
    assert "NOT_RUN" not in parsed["capability_checks"].values()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["check_evidence"].pop(PLANNED_CHECKS[0]),
        lambda payload: payload["check_evidence"].update({"unexpected": {}}),
        lambda payload: payload["check_evidence"].update({PLANNED_CHECKS[0]: "not-an-object"}),
        lambda payload: payload.update({"unexpected": True}),
    ],
)
def test_remote_json_rejects_inexact_evidence_schema(mutate: Any) -> None:
    module = _load_module()
    payload = _executed_remote_payload()
    mutate(payload)

    with pytest.raises(module.RehearsalError, match="schema"):
        module.parse_remote_json(json.dumps(payload))


def test_setup_result_keeps_checks_not_run_and_branches_ineligible() -> None:
    module = _load_module()
    plan = module.build_plan_result(ssh_host=DEFAULT_HOST)
    assert plan["planned_checks"] == list(PLANNED_CHECKS)
    for name in PLANNED_CHECKS:
        assert plan["capability_checks"][name] == "NOT_RUN"
    assert plan["branch_eligibility"]["PAUSED_TASK"] == "ineligible"
    assert plan["branch_eligibility"]["KUBELET_GAP"] == "ineligible"
    assert "PAUSED_TASK_ELIGIBLE" not in json.dumps(plan)
    assert "KUBELET_GAP_ELIGIBLE" not in json.dumps(plan)
    assert "CAPTURE_ONLY_PASS" not in json.dumps(plan)


def test_payload_is_fail_closed_and_excludes_prohibited_target_ops() -> None:
    module = _load_module()
    payload = module.REMOTE_PAYLOAD
    assert "set -eu" in payload or "set -e" in payload
    assert "umask" in payload
    assert module.SENTINEL_NAME in payload
    assert "trap" in payload
    assert "/tmp/agentflow-api-duckdb-capability-rehearsal/" in payload
    lowered = payload.lower()
    for token in FORBIDDEN_PAYLOAD_TOKENS:
        assert token.lower() not in lowered
    # Recursive removal must be gated by prefix + sentinel validation.
    assert "SENTINEL" in payload.upper() or module.SENTINEL_NAME in payload
    assert "rm -rf /" not in payload
    assert "kubectl" not in payload


def test_payload_implements_all_seven_bounded_scratch_checks() -> None:
    module = _load_module()
    payload = module.REMOTE_PAYLOAD
    required_tokens = (
        "time.monotonic_ns",
        "signal.SIGSTOP",
        "signal.SIGCONT",
        "watchdog",
        "lsof",
        "os.setxattr",
        "os.replace",
        "os.fsync",
        "check_evidence",
        EXECUTED_STATUS,
    )
    for token in required_tokens:
        assert token in payload

    for check_name in PLANNED_CHECKS:
        assert check_name in payload

    assert 'rm -rf -- "${SCRATCH_ROOT}/work"' in payload
    assert 'cat "${SCRATCH_ROOT}/${SENTINEL_NAME}"' in payload


def test_payload_keeps_target_claims_false_after_scratch_checks() -> None:
    module = _load_module()
    result = module.execute_rehearsal_setup(
        ssh_host=DEFAULT_HOST,
        run_id=RUN_ID,
        scratch_root=SAFE_SCRATCH_ROOT,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(_executed_remote_payload()),
            stderr="",
        ),
    )

    assert set(result["capability_checks"].values()) == {"PASS"}
    assert result["claim_boundary"]["i04_proved"] is False
    assert result["claim_boundary"]["i05_proved"] is False
    assert result["claim_boundary"]["i09_proved"] is False
    assert result["branch_eligibility"] == {
        "PAUSED_TASK": "ineligible",
        "KUBELET_GAP": "ineligible",
    }
