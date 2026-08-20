#!/usr/bin/env python3
"""Emit one fail-closed terminal record around a golden-soak controller run."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

SCHEMA_VERSION = 1
TERMINAL_PREFIX = "WRAPPER_RESULT="
EVIDENCE_WRITE_EXIT = 74
RESTORE_FAILURE_EXIT = 90
MAX_CONTROLLER_RESULT_BYTES = 4096
MAX_PLAN_BYTES = 16 * 1024

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PASS_PREFIXES = (
    "RESULT=REHEARSAL_PASS ",
    "RESULT=SOAK_PASS_DUAL_MEAN_90 ",
)


class Runner(Protocol):
    def run(self, argv: tuple[str, ...]) -> int: ...


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

    def as_dict(self) -> dict[str, object]:
        return {
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

    def encode(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


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
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("plan_invalid")
    return payload


def _plan_command(plan: dict[str, object], label: str) -> tuple[str, ...]:
    payload = plan.get(f"{label}_command")
    if (
        not isinstance(payload, list)
        or not payload
        or any(not isinstance(item, str) or not item or "\0" in item for item in payload)
    ):
        raise ValueError(f"{label}_command_invalid")
    return tuple(payload)


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
        plan = _load_plan(args.plan_path)
        controller_command = _plan_command(plan, "controller")
        restore_command = _plan_command(plan, "restore")
        controller_result_value = plan.get("controller_result_path")
        if (
            not isinstance(controller_result_value, str)
            or not controller_result_value
            or "\0" in controller_result_value
        ):
            raise ValueError("controller_result_path_invalid")
        record = execute_attempt(
            attempt_id=args.attempt_id,
            controller_command=controller_command,
            controller_result_path=Path(controller_result_value),
            restore_command=restore_command,
            runner=SubprocessRunner(),
        )
    except ValueError as exc:
        record = _configuration_failure(args.attempt_id, str(exc))
    return _emit_terminal(record, args.result_path)


if __name__ == "__main__":
    sys.exit(main())
