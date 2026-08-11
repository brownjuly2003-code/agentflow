#!/usr/bin/env python3
"""Fail-closed harness for a non-target API DuckDB capability rehearsal.

Default CLI mode emits a deterministic setup/plan JSON and never runs remote
commands. Isolated scratch execution runs seven bounded probes only after
``--execute``, the exact acknowledgement token, a validated run id, and a
unique path under the fixed scratch prefix. Scratch results do not prove
I04/I05/I09, approve a branch or runbook, or improve production status.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

SETUP_STATUS = "REHEARSAL_SETUP_READY_NOT_EXECUTED"
EXECUTED_REHEARSAL_STATUS = "NON_TARGET_SCRATCH_REHEARSAL_EXECUTED"
EXECUTION_ACK = "NON_TARGET_SCRATCH_REHEARSAL_ONLY"
DEFAULT_SSH_HOST = "deproject-mac"
SCRATCH_ROOT_PREFIX = "/tmp/agentflow-api-duckdb-capability-rehearsal/"  # noqa: S108
SENTINEL_NAME = ".agentflow-capability-rehearsal-sentinel"
DEFAULT_TIMEOUT_SECONDS = 60

RUN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")

PLANNED_CHECKS: tuple[str, ...] = (
    "timing/monotonic bounds",
    "scratch pause/resume behavior",
    "independent watchdog arm/fire/cancel behavior",
    "descriptor visibility on an exact scratch mount/path",
    "metadata tool/ACL/xattr capability",
    "same-directory atomic rename",
    "file and directory sync behavior",
)

PROTECTED_PATH_MARKERS: tuple[str, ...] = (
    "/var/lib/kubelet/pods/",
    "volumes/kubernetes.io~empty-dir/data",
    "c9d26829-c57f-4550-a86f-cdcc41e719fd",
    "agentflow-chk-restore-rv-api-20260802-01-59489dd45c-kk8tf",
    "8ed4b970504b8b702be7e01325a663bc7b3d91b3e8733c5c7fdb3bf6cf2e83bd",
    ".duckdb",
)

CLAIM_BOUNDARY: dict[str, Any] = {
    "authoritative_status": "CAPABILITY_REHEARSAL_REQUIRED",
    "preservation_status": "PRESERVATION_PARTIAL",
    "paused_task_eligible": False,
    "kubelet_gap_eligible": False,
    "i04_proved": False,
    "i05_proved": False,
    "i09_proved": False,
    "runbook_approved": False,
    "production_status_improved": False,
    "claim_scope": (
        "Non-target scratch capability rehearsal only. "
        "Does not prove I04/I05/I09, approve a runbook/branch, capture "
        "target bytes, or improve production readiness."
    ),
    "c10_boundary": (
        "Capture-only filesystem claim remains the outer design boundary; "
        "this harness does not assert a capture pass or branch eligibility."
    ),
}

REMOTE_RESULT_KEYS = frozenset(
    {
        "status",
        "execute",
        "capability_checks",
        "check_evidence",
        "branch_eligibility",
    }
)

REMOTE_PROBE_PYTHON = r"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

EXECUTED_STATUS = "NON_TARGET_SCRATCH_REHEARSAL_EXECUTED"
FIXED_PREFIX = "/tmp/agentflow-api-duckdb-capability-rehearsal/"
SENTINEL_NAME = ".agentflow-capability-rehearsal-sentinel"
CHECK_NAMES = (
    "timing/monotonic bounds",
    "scratch pause/resume behavior",
    "independent watchdog arm/fire/cancel behavior",
    "descriptor visibility on an exact scratch mount/path",
    "metadata tool/ACL/xattr capability",
    "same-directory atomic rename",
    "file and directory sync behavior",
)

run_id = sys.argv[1]
scratch_root = Path(sys.argv[2])
expected_root = Path(FIXED_PREFIX) / run_id
if scratch_root.as_posix() != expected_root.as_posix():
    raise RuntimeError("scratch root identity mismatch")
sentinel = scratch_root / SENTINEL_NAME
if not sentinel.is_file() or sentinel.read_text(encoding="utf-8").strip() != run_id:
    raise RuntimeError("scratch sentinel mismatch")
work_root = scratch_root / "work"
work_root.mkdir(mode=0o700)

capability_checks: dict[str, str] = {}
check_evidence: dict[str, dict[str, object]] = {}


def bounded_error(error: Exception) -> str:
    return str(error).replace("\n", " ")[:240]


def wait_until(predicate, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def stop_process(process: subprocess.Popen[str], *, continued: bool = True) -> None:
    if process.poll() is not None:
        return
    if not continued:
        os.kill(process.pid, signal.SIGCONT)
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def record(name: str, check) -> None:
    try:
        status, evidence = check()
        if status not in {"PASS", "PARTIAL", "BLOCKED"}:
            raise RuntimeError("invalid scratch status")
        if not isinstance(evidence, dict):
            raise RuntimeError("invalid scratch evidence")
    except Exception as error:
        status = "BLOCKED"
        evidence = {
            "error_type": type(error).__name__,
            "error": bounded_error(error),
        }
    evidence = {"scope": "non-target scratch only", **evidence}
    capability_checks[name] = status
    check_evidence[name] = evidence


def check_timing() -> tuple[str, dict[str, object]]:
    deltas: list[int] = []
    previous = time.monotonic_ns()
    for _ in range(2000):
        current = time.monotonic_ns()
        if current > previous:
            deltas.append(current - previous)
        previous = current
    if not deltas:
        return "BLOCKED", {"reason": "monotonic clock did not advance"}

    launch_latencies: list[int] = []
    for _ in range(3):
        started = time.monotonic_ns()
        completed = subprocess.run(
            [sys.executable, "-c", "pass"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        launch_latencies.append(time.monotonic_ns() - started)
        if completed.returncode != 0:
            return "BLOCKED", {"reason": "scratch process launch failed"}
    return "PASS", {
        "monotonic_resolution_ns": min(deltas),
        "process_launch_max_ns": max(launch_latencies),
        "samples": len(deltas),
        "target_timing_envelope_proved": False,
    }


def read_counter(path: Path) -> int:
    try:
        return int(path.read_text(encoding="ascii"))
    except (FileNotFoundError, ValueError):
        return -1


def check_pause_resume() -> tuple[str, dict[str, object]]:
    counter = work_root / "pause-counter"
    child_source = r'''
import os
import sys
import time
from pathlib import Path

counter = Path(sys.argv[1])
value = 0
while True:
    temporary = counter.with_suffix(".tmp")
    with temporary.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(str(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, counter)
    value += 1
    time.sleep(0.02)
'''
    process = subprocess.Popen(
        [sys.executable, "-c", child_source, str(counter)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    continued = True
    try:
        if not wait_until(lambda: read_counter(counter) >= 2, 2.0):
            return "BLOCKED", {"reason": "scratch writer did not advance"}
        os.kill(process.pid, signal.SIGSTOP)
        continued = False
        time.sleep(0.08)
        stopped_value = read_counter(counter)
        time.sleep(0.16)
        stable_value = read_counter(counter)
        os.kill(process.pid, signal.SIGCONT)
        continued = True
        resumed = wait_until(lambda: read_counter(counter) > stable_value, 2.0)
        if stopped_value < 0 or stable_value != stopped_value or not resumed:
            return "BLOCKED", {
                "stopped_value": stopped_value,
                "stable_value": stable_value,
                "resumed": resumed,
            }
        return "PASS", {
            "stopped_value": stopped_value,
            "stable_sample_seconds": 0.16,
            "resumed": True,
            "containerd_or_cgroup_proved": False,
        }
    finally:
        stop_process(process, continued=continued)
        counter.unlink(missing_ok=True)
        counter.with_suffix(".tmp").unlink(missing_ok=True)


def start_watchdog(marker: Path, delay_seconds: float) -> subprocess.Popen[str]:
    source = (
        "import sys,time; from pathlib import Path; "
        "time.sleep(float(sys.argv[2])); "
        "Path(sys.argv[1]).write_text('fired\\n', encoding='ascii')"
    )
    return subprocess.Popen(
        [sys.executable, "-c", source, str(marker), str(delay_seconds)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def check_watchdog() -> tuple[str, dict[str, object]]:
    fire_marker = work_root / "watchdog-fired"
    cancel_marker = work_root / "watchdog-cancelled"
    fired = start_watchdog(fire_marker, 0.12)
    started = time.monotonic_ns()
    try:
        fired.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        stop_process(fired)
        return "BLOCKED", {"reason": "scratch watchdog did not fire"}
    fire_latency_ns = time.monotonic_ns() - started
    if fired.returncode != 0 or not fire_marker.is_file():
        return "BLOCKED", {"reason": "scratch watchdog marker absent"}

    cancelled = start_watchdog(cancel_marker, 0.35)
    time.sleep(0.05)
    stop_process(cancelled)
    time.sleep(0.38)
    cancellation_held = not cancel_marker.exists()
    fire_marker.unlink(missing_ok=True)
    cancel_marker.unlink(missing_ok=True)
    if not cancellation_held:
        return "BLOCKED", {"reason": "cancelled watchdog still fired"}
    return "PASS", {
        "fire_latency_ns": fire_latency_ns,
        "cancellation_verified": True,
        "independent_scratch_process": True,
        "target_recovery_action_proved": False,
    }


def check_descriptors() -> tuple[str, dict[str, object]]:
    descriptor_path = work_root / "descriptor-probe"
    descriptor_path.write_text("scratch\n", encoding="ascii", newline="\n")
    resolved = descriptor_path.resolve(strict=True)
    with descriptor_path.open("rb"):
        proc_fd = Path("/proc/self/fd")
        if proc_fd.is_dir():
            visible = any(
                entry.resolve(strict=False) == resolved for entry in proc_fd.iterdir()
            )
            method = "proc-self-fd"
        else:
            lsof = shutil.which("lsof")
            if lsof is None:
                descriptor_path.unlink(missing_ok=True)
                return "BLOCKED", {"reason": "no descriptor inspection tool"}
            completed = subprocess.run(
                [lsof, "-F", "pn", "--", str(resolved)],
                check=False,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            visible = (
                completed.returncode == 0
                and f"p{os.getpid()}" in completed.stdout
                and f"n{resolved}" in completed.stdout
            )
            method = "lsof"
    descriptor_path.unlink(missing_ok=True)
    if not visible:
        return "BLOCKED", {"reason": "open scratch descriptor was not visible"}
    return "PASS", {
        "method": method,
        "exact_path_visible": True,
        "cross_namespace_target_proved": False,
    }


def check_metadata() -> tuple[str, dict[str, object]]:
    metadata_path = work_root / "metadata-probe"
    metadata_path.write_text("scratch\n", encoding="ascii", newline="\n")
    os.chmod(metadata_path, 0o640)
    xattr_roundtrip = False
    xattr_error = ""
    attribute = (
        "com.agentflow.rehearsal"
        if platform.system() == "Darwin"
        else "user.agentflow_rehearsal"
    )
    try:
        os.setxattr(metadata_path, attribute, b"scratch")
        xattr_roundtrip = os.getxattr(metadata_path, attribute) == b"scratch"
        os.removexattr(metadata_path, attribute)
    except (AttributeError, OSError) as error:
        xattr_error = bounded_error(error)

    acl_roundtrip = False
    acl_tools = "absent"
    getfacl = shutil.which("getfacl")
    setfacl = shutil.which("setfacl")
    if getfacl and setfacl:
        acl_tools = "getfacl/setfacl"
        set_result = subprocess.run(
            [setfacl, "-m", f"u:{os.getuid()}:r", str(metadata_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        get_result = subprocess.run(
            [getfacl, "-cp", str(metadata_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        acl_roundtrip = set_result.returncode == 0 and get_result.returncode == 0
        subprocess.run(
            [setfacl, "-b", str(metadata_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=3.0,
        )

    mode_preserved = metadata_path.stat().st_mode & 0o777 == 0o640
    metadata_path.unlink(missing_ok=True)
    if xattr_roundtrip and acl_roundtrip and mode_preserved:
        status = "PASS"
    elif xattr_roundtrip or acl_roundtrip:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    return status, {
        "mode_roundtrip": mode_preserved,
        "xattr_roundtrip": xattr_roundtrip,
        "xattr_error": xattr_error,
        "acl_roundtrip": acl_roundtrip,
        "acl_tools": acl_tools,
    }


def check_atomic_rename() -> tuple[str, dict[str, object]]:
    building = work_root / "rename.building"
    sealed = work_root / "rename.sealed"
    content = b"non-target scratch rename\n"
    building.write_bytes(content)
    same_device = building.stat().st_dev == work_root.stat().st_dev
    os.replace(building, sealed)
    valid = same_device and not building.exists() and sealed.read_bytes() == content
    sealed.unlink(missing_ok=True)
    if not valid:
        return "BLOCKED", {"reason": "same-directory replace verification failed"}
    return "PASS", {
        "same_device": True,
        "source_absent_after_replace": True,
        "destination_content_verified": True,
    }


def check_sync() -> tuple[str, dict[str, object]]:
    building = work_root / "sync.building"
    durable = work_root / "sync.durable"
    with building.open("wb") as stream:
        stream.write(b"non-target scratch sync\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(building, durable)
    directory_fd = os.open(work_root, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    durable_ok = durable.read_bytes() == b"non-target scratch sync\n"
    durable.unlink(missing_ok=True)
    if not durable_ok:
        return "BLOCKED", {"reason": "synced file content mismatch"}
    return "PASS", {
        "file_fsync": True,
        "same_directory_replace": True,
        "directory_fsync": True,
    }


record(CHECK_NAMES[0], check_timing)
record(CHECK_NAMES[1], check_pause_resume)
record(CHECK_NAMES[2], check_watchdog)
record(CHECK_NAMES[3], check_descriptors)
record(CHECK_NAMES[4], check_metadata)
record(CHECK_NAMES[5], check_atomic_rename)
record(CHECK_NAMES[6], check_sync)

print(
    json.dumps(
        {
            "status": EXECUTED_STATUS,
            "execute": True,
            "capability_checks": capability_checks,
            "check_evidence": check_evidence,
            "branch_eligibility": {
                "PAUSED_TASK": "ineligible",
                "KUBELET_GAP": "ineligible",
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )
)
"""


def _build_remote_payload() -> str:
    # Host, run id, and scratch root arrive as discrete argv entries after
    # ``bash -s --`` and are never shell-interpolated locally.
    blocked_outside = '{"status":"BLOCKED","reason":"scratch root outside fixed prefix"}'
    blocked_base = '{"status":"BLOCKED","reason":"scratch root must not be the base directory"}'
    blocked_match = '{"status":"BLOCKED","reason":"scratch root must equal prefix plus run id"}'
    blocked_exists = '{"status":"BLOCKED","reason":"scratch root must be a new empty path"}'
    blocked_base_type = '{"status":"BLOCKED","reason":"scratch base is not a plain directory"}'
    shell_prefix = f"""\
set -eu
umask 077

RUN_ID="${{1:?run id required}}"
SCRATCH_ROOT="${{2:?scratch root required}}"
FIXED_PREFIX="{SCRATCH_ROOT_PREFIX}"
SENTINEL_NAME="{SENTINEL_NAME}"
BASE_ROOT="${{FIXED_PREFIX%/}}"

case "${{SCRATCH_ROOT}}" in
  "${{FIXED_PREFIX}}"*)
    ;;
  *)
    printf '%s\\n' '{blocked_outside}' >&2
    exit 20
    ;;
esac

if [ "${{SCRATCH_ROOT}}" = "${{FIXED_PREFIX%/}}" ]; then
  printf '%s\\n' '{blocked_base}' >&2
  exit 21
fi
if [ "${{SCRATCH_ROOT}}" = "${{FIXED_PREFIX}}" ]; then
  printf '%s\\n' '{blocked_base}' >&2
  exit 21
fi

expected="${{FIXED_PREFIX}}${{RUN_ID}}"
if [ "${{SCRATCH_ROOT}}" != "${{expected}}" ]; then
  printf '%s\\n' '{blocked_match}' >&2
  exit 22
fi

if [ -e "${{SCRATCH_ROOT}}" ]; then
  printf '%s\\n' '{blocked_exists}' >&2
  exit 23
fi

if [ -e "${{BASE_ROOT}}" ]; then
  if [ ! -d "${{BASE_ROOT}}" ] || [ -L "${{BASE_ROOT}}" ]; then
    printf '%s\\n' '{blocked_base_type}' >&2
    exit 24
  fi
else
  mkdir -- "${{BASE_ROOT}}"
fi

cleanup() {{
  status=$?
  if [ "${{SCRATCH_ROOT:-}}" = "${{expected:-}}" ]; then
    if [ -f "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}" ]; then
      if [ "$(cat "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}")" = "${{RUN_ID}}" ]; then
        rm -rf -- "${{SCRATCH_ROOT}}/work"
        rm -f -- "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}"
        rmdir -- "${{SCRATCH_ROOT}}" 2>/dev/null || true
      fi
    fi
  fi
  return "${{status}}"
}}
trap cleanup EXIT

mkdir -- "${{SCRATCH_ROOT}}"
printf '%s\\n' "${{RUN_ID}}" > "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}"

python3 - "${{RUN_ID}}" "${{SCRATCH_ROOT}}" <<'PY'
"""
    return shell_prefix + REMOTE_PROBE_PYTHON + "\nPY\n"


REMOTE_PAYLOAD = _build_remote_payload()


class RehearsalError(RuntimeError):
    """Fail-closed blocked result for remote setup execution."""


def validate_run_id(run_id: str) -> str:
    if not run_id:
        raise ValueError("run id must be non-empty")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(
            "run id must match lowercase alphanumeric/hyphen pattern "
            "(segments of [a-z0-9] separated by single hyphens)"
        )
    return run_id


def validate_scratch_root(scratch_root: str, run_id: str) -> str:
    """Reject unsafe paths before any subprocess call.

    Accepted form is exactly ``SCRATCH_ROOT_PREFIX + run_id`` with no
    relative/ambiguous components and no protected target markers.
    """
    validated_run_id = validate_run_id(run_id)

    if scratch_root is None or scratch_root == "":
        raise ValueError("scratch root must be non-empty")
    if any(ch in scratch_root for ch in ("\x00", "\n", "\r")):
        raise ValueError("scratch root contains illegal characters")
    if not scratch_root.startswith("/"):
        raise ValueError("scratch root must be an absolute POSIX path")
    if scratch_root == "/":
        raise ValueError("scratch root must not be filesystem root")

    # Reject empty, ".", and ".." segments before normalization (symlink-
    # ambiguous / traversal / double-slash classes).
    segments = scratch_root.split("/")
    if segments[0] != "":
        raise ValueError("scratch root must be an absolute POSIX path")
    for segment in segments[1:]:
        if segment in ("", ".", ".."):
            raise ValueError(
                "scratch root is traversal-prone, normalization-ambiguous, or symlink-ambiguous"
            )

    normalized = PurePosixPath(scratch_root).as_posix()
    if normalized != scratch_root:
        raise ValueError("scratch root failed exact normalization match")

    prefix_no_slash = SCRATCH_ROOT_PREFIX.rstrip("/")
    if scratch_root == prefix_no_slash or scratch_root == SCRATCH_ROOT_PREFIX:
        raise ValueError("scratch root must not be the base rehearsal directory")

    if not scratch_root.startswith(SCRATCH_ROOT_PREFIX):
        raise ValueError(f"scratch root must be exactly beneath {SCRATCH_ROOT_PREFIX!r}")

    expected = f"{SCRATCH_ROOT_PREFIX}{validated_run_id}"
    if scratch_root != expected:
        raise ValueError("scratch root must be exactly the fixed prefix plus the run id")

    lowered = scratch_root.lower()
    for marker in PROTECTED_PATH_MARKERS:
        if marker.lower() in lowered:
            raise ValueError("scratch root references a protected target path")

    return scratch_root


def _not_run_checks() -> dict[str, str]:
    return dict.fromkeys(PLANNED_CHECKS, "NOT_RUN")


def _ineligible_branches() -> dict[str, str]:
    return {
        "PAUSED_TASK": "ineligible",
        "KUBELET_GAP": "ineligible",
    }


def build_plan_result(
    *,
    ssh_host: str = DEFAULT_SSH_HOST,
    run_id: str | None = None,
    scratch_root: str | None = None,
) -> dict[str, Any]:
    if not SAFE_SSH_HOST.fullmatch(ssh_host):
        raise ValueError(f"unsafe SSH host: {ssh_host!r}")
    return {
        "status": SETUP_STATUS,
        "execute": False,
        "ssh_host": ssh_host,
        "run_id": run_id,
        "scratch_root": scratch_root,
        "scratch_root_prefix": SCRATCH_ROOT_PREFIX,
        "acknowledgement_required": EXECUTION_ACK,
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "planned_checks": list(PLANNED_CHECKS),
        "capability_checks": _not_run_checks(),
        "branch_eligibility": _ineligible_branches(),
        "evidence_vocabulary": ["PASS", "PARTIAL", "BLOCKED", "NOT_RUN"],
    }


def build_ssh_argv(
    *,
    host: str,
    run_id: str,
    scratch_root: str,
    ssh_executable: str = "ssh",
    connect_timeout: int = 10,
) -> list[str]:
    if not SAFE_SSH_HOST.fullmatch(host):
        raise ValueError(f"unsafe SSH host: {host!r}")
    validated_run_id = validate_run_id(run_id)
    validated_root = validate_scratch_root(scratch_root, validated_run_id)
    return [
        ssh_executable,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=1",
        host,
        "bash",
        "-s",
        "--",
        validated_run_id,
        validated_root,
    ]


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RehearsalError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_remote_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise RehearsalError(f"malformed remote JSON: {error}") from error
    except RehearsalError:
        raise
    except TypeError as error:
        raise RehearsalError(f"malformed remote JSON: {error}") from error

    if not isinstance(payload, dict):
        raise RehearsalError("remote JSON schema mismatch: expected object")

    if set(payload) != REMOTE_RESULT_KEYS:
        raise RehearsalError(
            f"remote JSON schema mismatch: expected exactly {sorted(REMOTE_RESULT_KEYS)}"
        )
    if payload["status"] != EXECUTED_REHEARSAL_STATUS:
        raise RehearsalError("remote JSON schema mismatch: unexpected rehearsal status")
    if payload["execute"] is not True:
        raise RehearsalError("remote JSON schema mismatch: execute must be true")

    checks = payload.get("capability_checks")
    if not isinstance(checks, Mapping):
        raise RehearsalError("remote JSON schema mismatch: capability_checks must be an object")
    if set(checks) != set(PLANNED_CHECKS):
        raise RehearsalError("remote JSON schema mismatch: capability check set differs")
    allowed_statuses = {"PASS", "PARTIAL", "BLOCKED"}
    if any(checks[name] not in allowed_statuses for name in PLANNED_CHECKS):
        raise RehearsalError("remote JSON schema mismatch: invalid executed check status")

    evidence = payload.get("check_evidence")
    if not isinstance(evidence, Mapping):
        raise RehearsalError("remote JSON schema mismatch: check_evidence must be an object")
    if set(evidence) != set(PLANNED_CHECKS):
        raise RehearsalError("remote JSON schema mismatch: evidence check set differs")
    for name in PLANNED_CHECKS:
        item = evidence[name]
        if not isinstance(item, Mapping):
            raise RehearsalError(
                f"remote JSON schema mismatch: evidence for {name!r} must be an object"
            )
        if item.get("scope") != "non-target scratch only":
            raise RehearsalError(
                f"remote JSON schema mismatch: evidence for {name!r} has unsafe scope"
            )

    branches = payload.get("branch_eligibility")
    if not isinstance(branches, Mapping):
        raise RehearsalError("remote JSON schema mismatch: branch_eligibility must be an object")
    if branches != _ineligible_branches():
        raise RehearsalError("remote JSON schema mismatch: branches must remain ineligible")

    return payload


def _decode_process_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def execute_rehearsal_setup(
    *,
    ssh_host: str,
    run_id: str,
    scratch_root: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: (
        Callable[..., subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]] | None
    ) = None,
) -> dict[str, Any]:
    """Run the guarded non-target rehearsal once. Never retry on failure."""
    if not 5 <= timeout_seconds <= 300:
        raise ValueError("timeout must be between 5 and 300 seconds")

    argv = build_ssh_argv(
        host=ssh_host,
        run_id=run_id,
        scratch_root=scratch_root,
        connect_timeout=min(timeout_seconds, 10),
    )
    run = runner or subprocess.run
    try:
        completed = run(  # noqa: S603 - fixed argv vector, shell=False
            argv,
            input=REMOTE_PAYLOAD.encode("utf-8"),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RehearsalError("BLOCKED: remote scratch rehearsal timed out; no retry") from error
    except OSError as error:
        raise RehearsalError(f"BLOCKED: could not run scratch rehearsal: {error}") from error

    stdout = _decode_process_stream(completed.stdout)
    stderr = _decode_process_stream(completed.stderr)
    if completed.returncode != 0:
        detail = (stderr or stdout).strip()
        raise RehearsalError(
            f"BLOCKED: remote scratch rehearsal failed with nonzero exit "
            f"{completed.returncode}: {detail}"
        )

    remote = parse_remote_json(stdout)
    return {
        "status": remote["status"],
        "execute": True,
        "ssh_host": ssh_host,
        "run_id": run_id,
        "scratch_root": scratch_root,
        "scratch_root_prefix": SCRATCH_ROOT_PREFIX,
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "planned_checks": list(PLANNED_CHECKS),
        "capability_checks": {
            name: str(remote["capability_checks"][name]) for name in PLANNED_CHECKS
        },
        "check_evidence": {name: dict(remote["check_evidence"][name]) for name in PLANNED_CHECKS},
        "branch_eligibility": {
            "PAUSED_TASK": str(remote["branch_eligibility"]["PAUSED_TASK"]),
            "KUBELET_GAP": str(remote["branch_eligibility"]["KUBELET_GAP"]),
        },
        "evidence_vocabulary": ["PASS", "PARTIAL", "BLOCKED", "NOT_RUN"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default=DEFAULT_SSH_HOST)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=("run seven guarded non-target scratch probes over SSH (requires --acknowledge)"),
    )
    parser.add_argument(
        "--acknowledge",
        metavar="TOKEN",
        help=f"required with --execute; exact value: {EXECUTION_ACK}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)

    if arguments.execute and arguments.acknowledge != EXECUTION_ACK:
        print(
            f"error: --execute requires --acknowledge {EXECUTION_ACK}",
            file=sys.stderr,
        )
        return 2
    if not arguments.execute and arguments.acknowledge is not None:
        print("error: acknowledgement is only valid with --execute", file=sys.stderr)
        return 2

    try:
        if not arguments.execute:
            result = build_plan_result(
                ssh_host=arguments.ssh_host,
                run_id=arguments.run_id,
                scratch_root=arguments.scratch_root,
            )
        else:
            if arguments.run_id is None:
                print("error: --execute requires --run-id", file=sys.stderr)
                return 2
            if arguments.scratch_root is None:
                print("error: --execute requires --scratch-root", file=sys.stderr)
                return 2
            result = execute_rehearsal_setup(
                ssh_host=arguments.ssh_host,
                run_id=arguments.run_id,
                scratch_root=arguments.scratch_root,
                timeout_seconds=arguments.timeout_seconds,
            )
    except (RehearsalError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
