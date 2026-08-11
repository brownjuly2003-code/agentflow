#!/usr/bin/env python3
"""Fail-closed setup harness for a future non-target API DuckDB capability rehearsal.

Default CLI mode emits a deterministic setup/plan JSON and never runs remote
commands. Future isolated scratch execution requires ``--execute``, the exact
acknowledgement token, a validated run id, and a unique path under the fixed
scratch prefix. This slice does not prove I04/I05/I09, approve a branch or
runbook, or improve production status.
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
EXECUTED_SETUP_STATUS = "REHEARSAL_SETUP_EXECUTED"
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
        "Non-target scratch capability rehearsal setup only. "
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
        "branch_eligibility",
    }
)


def _remote_success_json() -> str:
    return json.dumps(
        {
            "status": EXECUTED_SETUP_STATUS,
            "execute": True,
            "capability_checks": dict.fromkeys(PLANNED_CHECKS, "NOT_RUN"),
            "branch_eligibility": {
                "PAUSED_TASK": "ineligible",
                "KUBELET_GAP": "ineligible",
            },
        },
        separators=(",", ":"),
    )


def _build_remote_payload() -> str:
    # Setup-only remote protocol. Host, run id, and scratch root arrive as
    # discrete argv entries after ``bash -s --`` and are never shell-
    # interpolated locally.
    blocked_outside = '{"status":"BLOCKED","reason":"scratch root outside fixed prefix"}'
    blocked_base = '{"status":"BLOCKED","reason":"scratch root must not be the base directory"}'
    blocked_match = '{"status":"BLOCKED","reason":"scratch root must equal prefix plus run id"}'
    blocked_exists = '{"status":"BLOCKED","reason":"scratch root must be a new empty path"}'
    success = _remote_success_json()
    return f"""\
set -eu
umask 077

RUN_ID="${{1:?run id required}}"
SCRATCH_ROOT="${{2:?scratch root required}}"
FIXED_PREFIX="{SCRATCH_ROOT_PREFIX}"
SENTINEL_NAME="{SENTINEL_NAME}"

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

cleanup() {{
  status=$?
  if [ -n "${{SCRATCH_ROOT:-}}" ] && [ -f "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}" ]; then
    case "${{SCRATCH_ROOT}}" in
      "${{FIXED_PREFIX}}"*)
        if [ -f "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}" ]; then
          rm -f -- "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}"
          rmdir -- "${{SCRATCH_ROOT}}" 2>/dev/null || true
        fi
        ;;
    esac
  fi
  return "${{status}}"
}}
trap cleanup EXIT

mkdir -- "${{SCRATCH_ROOT}}"
printf '%s\\n' "${{RUN_ID}}" > "${{SCRATCH_ROOT}}/${{SENTINEL_NAME}}"

printf '%s\\n' '{success}'
"""


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
    if payload["status"] != EXECUTED_SETUP_STATUS:
        raise RehearsalError("remote JSON schema mismatch: unexpected setup status")
    if payload["execute"] is not True:
        raise RehearsalError("remote JSON schema mismatch: execute must be true")

    checks = payload.get("capability_checks")
    if not isinstance(checks, Mapping):
        raise RehearsalError("remote JSON schema mismatch: capability_checks must be an object")
    if set(checks) != set(PLANNED_CHECKS):
        raise RehearsalError("remote JSON schema mismatch: capability check set differs")
    if any(checks[name] != "NOT_RUN" for name in PLANNED_CHECKS):
        raise RehearsalError("remote JSON schema mismatch: setup checks must remain NOT_RUN")

    branches = payload.get("branch_eligibility")
    if not isinstance(branches, Mapping):
        raise RehearsalError("remote JSON schema mismatch: branch_eligibility must be an object")
    if branches != _ineligible_branches():
        raise RehearsalError("remote JSON schema mismatch: branches must remain ineligible")

    return payload


def execute_rehearsal_setup(
    *,
    ssh_host: str,
    run_id: str,
    scratch_root: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Run the guarded setup payload once. Never retries on failure."""
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
            input=REMOTE_PAYLOAD,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RehearsalError("BLOCKED: remote rehearsal setup timed out; no retry") from error
    except OSError as error:
        raise RehearsalError(f"BLOCKED: could not run remote rehearsal setup: {error}") from error

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RehearsalError(
            f"BLOCKED: remote rehearsal setup failed with nonzero exit "
            f"{completed.returncode}: {detail}"
        )

    remote = parse_remote_json(completed.stdout)
    return {
        "status": remote.get("status", EXECUTED_SETUP_STATUS),
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
        help=("run the guarded non-target scratch setup once over SSH (requires --acknowledge)"),
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
