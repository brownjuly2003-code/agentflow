#!/usr/bin/env python3
"""Emit one fail-closed terminal record around a golden-soak controller run."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 2
TERMINAL_PREFIX = "WRAPPER_RESULT="
EVIDENCE_WRITE_EXIT = 74
RESTORE_FAILURE_EXIT = 90
MAX_CONTROLLER_RESULT_BYTES = 4096
MAX_PLAN_BYTES = 16 * 1024
MAX_PROBE_OUTPUT_BYTES = 1024
MAX_LOCK_OWNER_BYTES = 4096

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PASS_PREFIXES = (
    "RESULT=REHEARSAL_PASS ",
    "RESULT=SOAK_PASS_DUAL_MEAN_90 ",
)


class Runner(Protocol):
    def run(self, argv: tuple[str, ...]) -> int: ...

    def probe(self, argv: tuple[str, ...]) -> CommandResult: ...


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


class SubprocessRunner:
    def run(self, argv: tuple[str, ...]) -> int:
        completed = subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode

    def probe(self, argv: tuple[str, ...]) -> CommandResult:
        completed = subprocess.run(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if len(completed.stdout) > MAX_PROBE_OUTPUT_BYTES:
            output = ""
        else:
            try:
                output = completed.stdout.decode("utf-8")
            except UnicodeDecodeError:
                output = ""
        return CommandResult(returncode=completed.returncode, stdout=output)


@dataclass(frozen=True)
class ExactProbe:
    command: tuple[str, ...]
    expected_output: str


@dataclass(frozen=True)
class VisibilityProbe:
    command: tuple[str, ...]
    expected_sha256: str
    cleanup_command: tuple[str, ...]


@dataclass(frozen=True)
class ClickHouseProbes:
    container_health: ExactProbe
    host_route: ExactProbe
    workload_route: ExactProbe


@dataclass(frozen=True)
class KindRestoreContract:
    container_id: str
    identity_command: tuple[str, ...]
    running_command: tuple[str, ...]
    restart_count_command: tuple[str, ...]
    apiserver_count_command: tuple[str, ...]
    livez_command: tuple[str, ...]
    livez_max_attempts: int
    livez_consecutive_successes: int


@dataclass(frozen=True)
class GuardedPlan:
    shared_root: Path
    snapshot_path: Path
    output_parent_path: Path
    owner_lock_path: Path
    source_probe: VisibilityProbe
    output_probe: VisibilityProbe
    clickhouse: ClickHouseProbes
    stop_command: tuple[str, ...]
    controller_command: tuple[str, ...]
    controller_result_path: Path
    restore_command: tuple[str, ...]
    kind_restore: KindRestoreContract


@dataclass(frozen=True)
class CheckRecord:
    name: str
    phase: str
    result: str
    classification: str
    reason: str
    returncode: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "name": self.name,
            "phase": self.phase,
            "reason": self.reason,
            "result": self.result,
            "returncode": self.returncode,
        }


@dataclass(frozen=True)
class TerminalRecord:
    attempt_id: str
    controller_invocation: str
    failure_class: str
    first_boundary: str
    primary_rc: int | None
    primary_result: str
    reason: str
    restore_rc: int | None
    restore_result: str
    result: str
    schema_version: int = SCHEMA_VERSION
    checks: tuple[CheckRecord, ...] = ()
    lock_result: str | None = None
    stop_rc: int | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "attempt_id": self.attempt_id,
            "controller_invocation": self.controller_invocation,
            "failure_class": self.failure_class,
            "first_boundary": self.first_boundary,
            "primary_rc": self.primary_rc,
            "primary_result": self.primary_result,
            "reason": self.reason,
            "restore_rc": self.restore_rc,
            "restore_result": self.restore_result,
            "result": self.result,
            "schema_version": self.schema_version,
        }
        if self.lock_result is not None:
            payload["checks"] = [check.as_dict() for check in self.checks]
            payload["lock_result"] = self.lock_result
            payload["stop_rc"] = self.stop_rc
        return payload

    def encode(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class OwnerLockError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ExclusiveOwnerLock:
    def __init__(self, path: Path, attempt_id: str) -> None:
        self.path = path
        self.attempt_id = attempt_id
        self._token: str | None = None

    @property
    def owner_path(self) -> Path:
        return self.path / "owner.json"

    @staticmethod
    def _valid_owner(payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("schema_version") == 1
            and isinstance(payload.get("attempt_id"), str)
            and bool(_ATTEMPT_ID_RE.fullmatch(payload["attempt_id"]))
            and isinstance(payload.get("pid"), int)
            and payload["pid"] > 0
            and isinstance(payload.get("token"), str)
            and bool(re.fullmatch(r"[0-9a-f]{32}", payload["token"]))
            and isinstance(payload.get("acquired_utc"), str)
            and bool(payload["acquired_utc"])
        )

    def _read_owner(self) -> dict[str, object]:
        try:
            raw = self.owner_path.read_bytes()
        except OSError as exc:
            raise OwnerLockError("owner_lock_state_invalid") from exc
        if not raw or len(raw) > MAX_LOCK_OWNER_BYTES:
            raise OwnerLockError("owner_lock_state_invalid")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OwnerLockError("owner_lock_state_invalid") from exc
        if not self._valid_owner(payload):
            raise OwnerLockError("owner_lock_state_invalid")
        return payload

    def acquire(self) -> None:
        if not _ATTEMPT_ID_RE.fullmatch(self.attempt_id):
            raise OwnerLockError("owner_lock_attempt_invalid")
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError as exc:
            self._read_owner()
            raise OwnerLockError("owner_lock_busy") from exc
        except OSError as exc:
            raise OwnerLockError("owner_lock_unavailable") from exc

        token = uuid.uuid4().hex
        payload = {
            "acquired_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "attempt_id": self.attempt_id,
            "pid": os.getpid(),
            "schema_version": 1,
            "token": token,
        }
        try:
            self.owner_path.write_text(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            try:
                self.path.rmdir()
            except OSError:
                pass
            raise OwnerLockError("owner_lock_unavailable") from exc
        self._token = token

    def release(self) -> None:
        if self._token is None:
            raise OwnerLockError("owner_lock_release_failed")
        try:
            entries = list(self.path.iterdir())
        except OSError as exc:
            raise OwnerLockError("owner_lock_release_failed") from exc
        if entries != [self.owner_path]:
            raise OwnerLockError("owner_lock_release_failed")
        try:
            owner = self._read_owner()
        except OwnerLockError as exc:
            raise OwnerLockError("owner_lock_release_failed") from exc
        if owner["token"] != self._token:
            raise OwnerLockError("owner_lock_release_failed")
        try:
            self.owner_path.unlink()
            self.path.rmdir()
        except OSError as exc:
            raise OwnerLockError("owner_lock_release_failed") from exc
        self._token = None


def _valid_command(command: tuple[str, ...]) -> bool:
    return bool(command) and all(item and "\0" not in item for item in command)


def _normalized_probe_output(output: str) -> str | None:
    if len(output.encode("utf-8")) > MAX_PROBE_OUTPUT_BYTES:
        return None
    lines = output.splitlines()
    if len(lines) != 1 or not lines[0] or "\0" in lines[0]:
        return None
    return lines[0]


def _read_controller_result(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return "MISSING"
    if not raw or len(raw) > MAX_CONTROLLER_RESULT_BYTES:
        return "INVALID"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "INVALID"
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0]:
        return "INVALID"
    return lines[0]


def _is_controller_pass(result: str) -> bool:
    return result.startswith(_PASS_PREFIXES)


def execute_attempt(
    *,
    attempt_id: str,
    controller_command: tuple[str, ...],
    controller_result_path: Path,
    restore_command: tuple[str, ...],
    runner: Runner,
) -> TerminalRecord:
    if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise ValueError("attempt_identity_invalid")
    if not controller_command:
        raise ValueError("controller_command_invalid")
    if not restore_command:
        raise ValueError("restore_command_invalid")

    controller_invocation = "NOT_INVOKED"
    primary_rc: int | None = None
    primary_result = "NOT_INVOKED"
    failure_class = "NONE"
    first_boundary = "complete"
    reason = "ok"
    candidate_pass = False

    try:
        primary_rc = runner.run(controller_command)
        controller_invocation = "INVOKED"
        primary_result = _read_controller_result(controller_result_path)
        if primary_rc != 0:
            failure_class = "CONTROLLER_FAILURE"
            first_boundary = "controller"
            reason = "controller_failed"
        elif not _is_controller_pass(primary_result):
            failure_class = "CONTROLLER_FAILURE"
            first_boundary = "controller"
            reason = (
                "controller_result_missing"
                if primary_result == "MISSING"
                else "controller_result_invalid"
            )
        else:
            candidate_pass = True
    except OSError:
        failure_class = "WRAPPER_FAILURE"
        first_boundary = "controller_launch"
        reason = "controller_not_invoked"

    restore_rc: int | None = None
    restore_result = "NOT_INVOKED"
    try:
        restore_rc = runner.run(restore_command)
        restore_result = "PASS" if restore_rc == 0 else "FAIL"
    except OSError:
        pass

    if candidate_pass and restore_result != "PASS":
        failure_class = "WRAPPER_FAILURE"
        first_boundary = "restore"
        reason = "restore_not_invoked" if restore_rc is None else "restore_failed"
        candidate_pass = False

    return TerminalRecord(
        attempt_id=attempt_id,
        controller_invocation=controller_invocation,
        failure_class=failure_class,
        first_boundary=first_boundary,
        primary_rc=primary_rc,
        primary_result=primary_result,
        reason=reason,
        restore_rc=restore_rc,
        restore_result=restore_result,
        result="PASS" if candidate_pass else "FAIL",
    )


def _probe_check(
    *,
    runner: Runner,
    probe: ExactProbe,
    name: str,
    phase: str,
    classification: str,
    reason: str,
) -> CheckRecord:
    returncode: int | None = None
    observed: str | None = None
    try:
        command_result = runner.probe(probe.command)
        returncode = command_result.returncode
        observed = _normalized_probe_output(command_result.stdout)
    except OSError:
        pass
    passed = returncode == 0 and observed == probe.expected_output
    return CheckRecord(
        name=name,
        phase=phase,
        result="PASS" if passed else "FAIL",
        classification="NONE" if passed else classification,
        reason="ok" if passed else reason,
        returncode=returncode,
    )


def _path_policy_checks(plan: GuardedPlan) -> tuple[list[CheckRecord], str | None]:
    checks: list[CheckRecord] = []
    try:
        shared_root = plan.shared_root.resolve(strict=True)
    except OSError:
        return checks, "shared_root_invalid"
    if not shared_root.is_dir() or plan.shared_root.is_symlink():
        return checks, "shared_root_invalid"

    for name, path, outside_reason in (
        ("snapshot_containment", plan.snapshot_path, "snapshot_outside_shared_root"),
        (
            "output_parent_containment",
            plan.output_parent_path,
            "output_parent_outside_shared_root",
        ),
    ):
        passed = False
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(shared_root)
            passed = resolved != shared_root and resolved.is_dir() and not path.is_symlink()
        except (OSError, ValueError):
            pass
        checks.append(
            CheckRecord(
                name=name,
                phase="path_policy",
                result="PASS" if passed else "FAIL",
                classification="NONE" if passed else "PATH_POLICY_FAILURE",
                reason="ok" if passed else outside_reason,
                returncode=None,
            )
        )
        if not passed:
            return checks, outside_reason

    try:
        controller_parent = plan.controller_result_path.parent.resolve(strict=True)
        output_parent = plan.output_parent_path.resolve(strict=True)
    except OSError:
        return checks, "controller_result_parent_invalid"
    if controller_parent != output_parent:
        return checks, "controller_result_parent_invalid"
    return checks, None


def _visibility_checks(plan: GuardedPlan, runner: Runner) -> list[CheckRecord]:
    checks: list[CheckRecord] = []
    for label, visibility in (
        ("source", plan.source_probe),
        ("output", plan.output_probe),
    ):
        checks.append(
            _probe_check(
                runner=runner,
                probe=ExactProbe(visibility.command, visibility.expected_sha256),
                name=f"{label}_visibility",
                phase="daemon_visibility_preflight",
                classification=f"{label.upper()}_VISIBILITY_FAILURE",
                reason=f"{label}_visibility_failed",
            )
        )
        checks.append(
            _probe_check(
                runner=runner,
                probe=ExactProbe(visibility.cleanup_command, "absent"),
                name=f"{label}_probe_cleanup",
                phase="daemon_visibility_preflight",
                classification="PROBE_CLEANUP_FAILURE",
                reason=f"{label}_probe_cleanup_failed",
            )
        )
    return checks


def _clickhouse_checks(plan: GuardedPlan, runner: Runner) -> list[CheckRecord]:
    checks: list[CheckRecord] = []
    for name, probe, classification, reason in (
        (
            "clickhouse_container_health",
            plan.clickhouse.container_health,
            "SERVICE_HEALTH_FAILURE",
            "clickhouse_container_health_failed",
        ),
        (
            "clickhouse_host_route",
            plan.clickhouse.host_route,
            "HOST_ROUTE_FAILURE",
            "clickhouse_host_route_failed",
        ),
        (
            "clickhouse_workload_route",
            plan.clickhouse.workload_route,
            "WORKLOAD_ROUTE_FAILURE",
            "clickhouse_workload_route_failed",
        ),
    ):
        checks.append(
            _probe_check(
                runner=runner,
                probe=probe,
                name=name,
                phase="clickhouse_preflight",
                classification=classification,
                reason=reason,
            )
        )
    return checks


def _guarded_failure(
    *,
    attempt_id: str,
    failure_class: str,
    first_boundary: str,
    reason: str,
    checks: list[CheckRecord],
    stop_rc: int | None = None,
) -> TerminalRecord:
    return TerminalRecord(
        attempt_id=attempt_id,
        controller_invocation="NOT_INVOKED",
        failure_class=failure_class,
        first_boundary=first_boundary,
        primary_rc=None,
        primary_result="NOT_INVOKED",
        reason=reason,
        restore_rc=None,
        restore_result="NOT_INVOKED",
        result="FAIL",
        checks=tuple(checks),
        lock_result="ACQUIRED",
        stop_rc=stop_rc,
    )


def _invoke_guarded_controller(
    *,
    attempt_id: str,
    plan: GuardedPlan,
    runner: Runner,
    checks: list[CheckRecord],
    stop_rc: int,
) -> TerminalRecord:
    controller_invocation = "NOT_INVOKED"
    primary_rc: int | None = None
    primary_result = "NOT_INVOKED"
    failure_class = "NONE"
    first_boundary = "complete"
    reason = "ok"
    candidate_pass = False
    try:
        primary_rc = runner.run(plan.controller_command)
        controller_invocation = "INVOKED"
        primary_result = _read_controller_result(plan.controller_result_path)
        if primary_rc != 0:
            failure_class = "CONTROLLER_FAILURE"
            first_boundary = "controller"
            reason = "controller_failed"
        elif not _is_controller_pass(primary_result):
            failure_class = "CONTROLLER_FAILURE"
            first_boundary = "controller"
            reason = (
                "controller_result_missing"
                if primary_result == "MISSING"
                else "controller_result_invalid"
            )
        else:
            candidate_pass = True
    except OSError:
        failure_class = "WRAPPER_FAILURE"
        first_boundary = "controller_launch"
        reason = "controller_not_invoked"

    return TerminalRecord(
        attempt_id=attempt_id,
        controller_invocation=controller_invocation,
        failure_class=failure_class,
        first_boundary=first_boundary,
        primary_rc=primary_rc,
        primary_result=primary_result,
        reason=reason,
        restore_rc=None,
        restore_result="NOT_INVOKED",
        result="PASS" if candidate_pass else "FAIL",
        checks=tuple(checks),
        lock_result="ACQUIRED",
        stop_rc=stop_rc,
    )


def _kind_restore_checks(
    plan: GuardedPlan,
    runner: Runner,
) -> tuple[list[CheckRecord], str | None, str | None]:
    contract = plan.kind_restore
    checks: list[CheckRecord] = []
    for name, command, expected, classification, reason, boundary in (
        (
            "kind_container_identity",
            contract.identity_command,
            contract.container_id,
            "KIND_IDENTITY_FAILURE",
            "kind_container_identity_mismatch",
            "restore_kind_identity",
        ),
        (
            "kind_container_running",
            contract.running_command,
            "running",
            "KIND_STATE_FAILURE",
            "kind_container_not_running",
            "restore_kind_state",
        ),
        (
            "kind_container_restart_count",
            contract.restart_count_command,
            "0",
            "KIND_STATE_FAILURE",
            "kind_container_restarted",
            "restore_kind_state",
        ),
        (
            "kind_apiserver_count",
            contract.apiserver_count_command,
            "1",
            "KIND_APISERVER_FAILURE",
            "kind_apiserver_count_invalid",
            "restore_kind_apiserver",
        ),
    ):
        check = _probe_check(
            runner=runner,
            probe=ExactProbe(command, expected),
            name=name,
            phase="kind_restore",
            classification=classification,
            reason=reason,
        )
        checks.append(check)
        if check.result != "PASS":
            return checks, reason, boundary

    consecutive = 0
    for attempt in range(1, contract.livez_max_attempts + 1):
        check = _probe_check(
            runner=runner,
            probe=ExactProbe(contract.livez_command, "ok"),
            name=f"kind_livez_{attempt}",
            phase="kind_restore",
            classification="KIND_LIVEZ_PENDING",
            reason="kind_livez_pending",
        )
        checks.append(check)
        consecutive = consecutive + 1 if check.result == "PASS" else 0
        if consecutive >= contract.livez_consecutive_successes:
            return checks, None, None
    return checks, "kind_livez_not_ready", "restore_kind_livez"


def _apply_guarded_restore(
    record: TerminalRecord,
    *,
    plan: GuardedPlan,
    runner: Runner,
) -> TerminalRecord:
    checks = list(record.checks)
    restore_rc: int | None = None
    restore_result = "FAIL"
    failure_class = "WRAPPER_FAILURE"
    first_boundary = "restore"
    reason = "restore_not_invoked"
    try:
        restore_rc = runner.run(plan.restore_command)
    except OSError:
        pass
    else:
        if restore_rc != 0:
            reason = "restore_failed"
        else:
            kind_checks, kind_reason, kind_boundary = _kind_restore_checks(plan, runner)
            checks.extend(kind_checks)
            if kind_reason is None:
                restore_result = "PASS"
            else:
                failure_class = "INFRASTRUCTURE_CONTRACT_FAILURE"
                first_boundary = kind_boundary or "restore_kind"
                reason = kind_reason

    updated = replace(
        record,
        checks=tuple(checks),
        restore_rc=restore_rc,
        restore_result=restore_result,
    )
    if record.result == "PASS" and restore_result != "PASS":
        return replace(
            updated,
            failure_class=failure_class,
            first_boundary=first_boundary,
            reason=reason,
            result="FAIL",
        )
    return updated


def _validate_guarded_plan(plan: GuardedPlan) -> None:
    commands = (
        plan.source_probe.command,
        plan.source_probe.cleanup_command,
        plan.output_probe.command,
        plan.output_probe.cleanup_command,
        plan.clickhouse.container_health.command,
        plan.clickhouse.host_route.command,
        plan.clickhouse.workload_route.command,
        plan.stop_command,
        plan.controller_command,
        plan.restore_command,
        plan.kind_restore.identity_command,
        plan.kind_restore.running_command,
        plan.kind_restore.restart_count_command,
        plan.kind_restore.apiserver_count_command,
        plan.kind_restore.livez_command,
    )
    if any(not _valid_command(command) for command in commands):
        raise ValueError("guarded_command_invalid")
    if not _SHA256_RE.fullmatch(plan.source_probe.expected_sha256):
        raise ValueError("source_probe_sha256_invalid")
    if not _SHA256_RE.fullmatch(plan.output_probe.expected_sha256):
        raise ValueError("output_probe_sha256_invalid")
    for probe in (
        plan.clickhouse.container_health,
        plan.clickhouse.host_route,
        plan.clickhouse.workload_route,
    ):
        if _normalized_probe_output(probe.expected_output) != probe.expected_output:
            raise ValueError("clickhouse_probe_output_invalid")
    contract = plan.kind_restore
    if not _CONTAINER_ID_RE.fullmatch(contract.container_id):
        raise ValueError("kind_container_id_invalid")
    if type(contract.livez_max_attempts) is not int or not (
        2 <= contract.livez_max_attempts <= 120
    ):
        raise ValueError("kind_livez_attempts_invalid")
    if type(contract.livez_consecutive_successes) is not int or not (
        2 <= contract.livez_consecutive_successes <= contract.livez_max_attempts
    ):
        raise ValueError("kind_livez_consecutive_invalid")


def execute_guarded_attempt(
    *,
    attempt_id: str,
    plan: GuardedPlan,
    runner: Runner,
) -> TerminalRecord:
    if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
        raise ValueError("attempt_identity_invalid")
    _validate_guarded_plan(plan)

    lock = ExclusiveOwnerLock(plan.owner_lock_path, attempt_id)
    try:
        lock.acquire()
    except OwnerLockError as exc:
        return replace(
            _guarded_failure(
                attempt_id=attempt_id,
                failure_class="WRAPPER_FAILURE",
                first_boundary="owner_lock",
                reason=exc.reason,
                checks=[],
            ),
            lock_result=exc.reason.removeprefix("owner_lock_").upper(),
        )

    checks, path_failure = _path_policy_checks(plan)
    record: TerminalRecord | None = None
    stopped = False
    if path_failure is not None:
        record = _guarded_failure(
            attempt_id=attempt_id,
            failure_class="INFRASTRUCTURE_CONTRACT_FAILURE",
            first_boundary="path_policy",
            reason=path_failure,
            checks=checks,
        )

    if record is None:
        visibility_checks = _visibility_checks(plan, runner)
        checks.extend(visibility_checks)
        visibility_failure = next(
            (check for check in visibility_checks if check.result != "PASS"), None
        )
        if visibility_failure is not None:
            record = _guarded_failure(
                attempt_id=attempt_id,
                failure_class="INFRASTRUCTURE_CONTRACT_FAILURE",
                first_boundary="daemon_visibility_preflight",
                reason=visibility_failure.reason,
                checks=checks,
            )

    if record is None:
        clickhouse_checks = _clickhouse_checks(plan, runner)
        checks.extend(clickhouse_checks)
        clickhouse_failure = next(
            (check for check in clickhouse_checks if check.result != "PASS"), None
        )
        if clickhouse_failure is not None:
            record = _guarded_failure(
                attempt_id=attempt_id,
                failure_class="INFRASTRUCTURE_CONTRACT_FAILURE",
                first_boundary="clickhouse_preflight",
                reason=clickhouse_failure.reason,
                checks=checks,
            )

    if record is None:
        stopped = True
        stop_rc: int | None = None
        try:
            stop_rc = runner.run(plan.stop_command)
        except OSError:
            pass
        if stop_rc != 0:
            record = _guarded_failure(
                attempt_id=attempt_id,
                failure_class="WRAPPER_FAILURE",
                first_boundary="co_tenant_stop",
                reason=(
                    "co_tenant_stop_not_invoked" if stop_rc is None else "co_tenant_stop_failed"
                ),
                checks=checks,
                stop_rc=stop_rc,
            )
        else:
            record = _invoke_guarded_controller(
                attempt_id=attempt_id,
                plan=plan,
                runner=runner,
                checks=checks,
                stop_rc=stop_rc,
            )

    if stopped:
        record = _apply_guarded_restore(record, plan=plan, runner=runner)

    lock_result = "RELEASED"
    try:
        lock.release()
    except OwnerLockError:
        lock_result = "RELEASE_FAILED"
        if record.result == "PASS":
            record = replace(
                record,
                failure_class="WRAPPER_FAILURE",
                first_boundary="owner_lock_release",
                reason="owner_lock_release_failed",
                result="FAIL",
            )
    return replace(record, lock_result=lock_result)


def _load_plan(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError("plan_invalid") from exc
    if not raw or len(raw) > MAX_PLAN_BYTES:
        raise ValueError("plan_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("plan_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("plan_invalid")
    return payload


def _payload_command(payload: dict[str, object], key: str, invalid_reason: str) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or "\0" in item for item in value)
    ):
        raise ValueError(invalid_reason)
    return tuple(value)


def _plan_command(plan: dict[str, object], label: str) -> tuple[str, ...]:
    return _payload_command(plan, f"{label}_command", f"{label}_command_invalid")


def _payload_mapping(
    payload: dict[str, object], key: str, invalid_reason: str
) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(invalid_reason)
    return value


def _payload_text(payload: dict[str, object], key: str, invalid_reason: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(invalid_reason)
    return value


def _plan_path(plan: dict[str, object], label: str) -> Path:
    path = Path(_payload_text(plan, label, f"{label}_invalid"))
    if not path.is_absolute():
        raise ValueError(f"{label}_invalid")
    return path


def _visibility_probe(plan: dict[str, object], label: str) -> VisibilityProbe:
    payload = _payload_mapping(plan, f"{label}_probe", f"{label}_probe_invalid")
    return VisibilityProbe(
        command=_payload_command(payload, "command", f"{label}_probe_command_invalid"),
        expected_sha256=_payload_text(payload, "expected_sha256", f"{label}_probe_sha256_invalid"),
        cleanup_command=_payload_command(
            payload, "cleanup_command", f"{label}_probe_cleanup_command_invalid"
        ),
    )


def _exact_probe(payload: dict[str, object], label: str) -> ExactProbe:
    probe = _payload_mapping(payload, label, f"{label}_probe_invalid")
    return ExactProbe(
        command=_payload_command(probe, "command", f"{label}_probe_command_invalid"),
        expected_output=_payload_text(probe, "expected_output", f"{label}_probe_output_invalid"),
    )


def _guarded_plan_from_payload(plan: dict[str, object]) -> GuardedPlan:
    clickhouse = _payload_mapping(plan, "clickhouse_probes", "clickhouse_probes_invalid")
    kind = _payload_mapping(plan, "kind_restore", "kind_restore_invalid")
    livez_max_attempts = kind.get("livez_max_attempts")
    livez_consecutive_successes = kind.get("livez_consecutive_successes")
    if type(livez_max_attempts) is not int:
        raise ValueError("kind_livez_attempts_invalid")
    if type(livez_consecutive_successes) is not int:
        raise ValueError("kind_livez_consecutive_invalid")
    guarded = GuardedPlan(
        shared_root=_plan_path(plan, "shared_root"),
        snapshot_path=_plan_path(plan, "snapshot_path"),
        output_parent_path=_plan_path(plan, "output_parent_path"),
        owner_lock_path=_plan_path(plan, "owner_lock_path"),
        source_probe=_visibility_probe(plan, "source"),
        output_probe=_visibility_probe(plan, "output"),
        clickhouse=ClickHouseProbes(
            container_health=_exact_probe(clickhouse, "container_health"),
            host_route=_exact_probe(clickhouse, "host_route"),
            workload_route=_exact_probe(clickhouse, "workload_route"),
        ),
        stop_command=_plan_command(plan, "stop"),
        controller_command=_plan_command(plan, "controller"),
        controller_result_path=_plan_path(plan, "controller_result_path"),
        restore_command=_plan_command(plan, "restore"),
        kind_restore=KindRestoreContract(
            container_id=_payload_text(kind, "container_id", "kind_container_id_invalid"),
            identity_command=_payload_command(
                kind, "identity_command", "kind_identity_command_invalid"
            ),
            running_command=_payload_command(
                kind, "running_command", "kind_running_command_invalid"
            ),
            restart_count_command=_payload_command(
                kind, "restart_count_command", "kind_restart_count_command_invalid"
            ),
            apiserver_count_command=_payload_command(
                kind,
                "apiserver_count_command",
                "kind_apiserver_count_command_invalid",
            ),
            livez_command=_payload_command(kind, "livez_command", "kind_livez_command_invalid"),
            livez_max_attempts=livez_max_attempts,
            livez_consecutive_successes=livez_consecutive_successes,
        ),
    )
    _validate_guarded_plan(guarded)
    return guarded


def _configuration_failure(attempt_id: str, reason: str) -> TerminalRecord:
    return TerminalRecord(
        attempt_id=attempt_id,
        controller_invocation="NOT_INVOKED",
        failure_class="WRAPPER_FAILURE",
        first_boundary="wrapper_config",
        primary_rc=None,
        primary_result="NOT_INVOKED",
        reason=reason,
        restore_rc=None,
        restore_result="NOT_INVOKED",
        result="FAIL",
    )


def _atomic_write(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _emit_terminal(record: TerminalRecord, result_path: Path) -> int:
    try:
        _atomic_write(result_path, record.encode())
    except OSError:
        record = replace(
            record,
            failure_class="WRAPPER_FAILURE",
            first_boundary="terminal_record",
            reason="terminal_record_write_failed",
            result="FAIL",
        )
        print(TERMINAL_PREFIX + record.encode(), flush=True)
        return EVIDENCE_WRITE_EXIT

    print(TERMINAL_PREFIX + record.encode(), flush=True)
    if record.result == "PASS":
        return 0
    if record.first_boundary == "restore":
        return RESTORE_FAILURE_EXIT
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--result-path", required=True, type=Path)
    parser.add_argument("--plan-path", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not _ATTEMPT_ID_RE.fullmatch(args.attempt_id):
            raise ValueError("attempt_identity_invalid")
        plan = _guarded_plan_from_payload(_load_plan(args.plan_path))
        try:
            result_parent = args.result_path.parent.resolve(strict=True)
            output_parent = plan.output_parent_path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("wrapper_result_parent_invalid") from exc
        if result_parent != output_parent or args.result_path.exists():
            raise ValueError("wrapper_result_path_invalid")
        if args.result_path.resolve(strict=False) == plan.controller_result_path.resolve(
            strict=False
        ):
            raise ValueError("wrapper_result_path_invalid")
        record = execute_guarded_attempt(
            attempt_id=args.attempt_id,
            plan=plan,
            runner=SubprocessRunner(),
        )
    except ValueError as exc:
        record = _configuration_failure(args.attempt_id, str(exc))
    return _emit_terminal(record, args.result_path)


if __name__ == "__main__":
    sys.exit(main())
