#!/usr/bin/env python3
"""Collect bounded, read-only Colima and kind runtime diagnostics over SSH."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
REMOTE_PATH = "/Users/julia/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
MAX_CAPTURE_CHARS = 32_768


class DiagnosticConfig:
    """Validated identifiers and bounds for a diagnostic collection."""

    __slots__ = ("ssh_host", "colima_profile", "timeout_seconds")

    def __init__(
        self,
        *,
        ssh_host: str,
        colima_profile: str,
        timeout_seconds: int,
    ) -> None:
        if not SAFE_SSH_HOST.fullmatch(ssh_host):
            raise ValueError(f"unsafe SSH host: {ssh_host!r}")
        if not SAFE_IDENTIFIER.fullmatch(colima_profile):
            raise ValueError(f"unsafe colima profile: {colima_profile!r}")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("timeout must be between 1 and 120 seconds")
        self.ssh_host = ssh_host
        self.colima_profile = colima_profile
        self.timeout_seconds = timeout_seconds


class CheckSpec(NamedTuple):
    name: str
    command: str


class CheckResult(NamedTuple):
    name: str
    status: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


def _text_from_timeout(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _bounded(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n[output truncated]\n"


class ReadOnlySshClient:
    """Run one fixed read-only check per SSH process with an independent timeout."""

    def __init__(self, *, host: str, timeout_seconds: int, executable: str = "ssh") -> None:
        if not SAFE_SSH_HOST.fullmatch(host):
            raise ValueError(f"unsafe SSH host: {host!r}")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("timeout must be between 1 and 120 seconds")
        self._host = host
        self._timeout_seconds = timeout_seconds
        self._executable = executable

    def run(self, name: str, command: str) -> CheckResult:
        connect_timeout = min(self._timeout_seconds, 10)
        arguments = [
            self._executable,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=1",
            self._host,
            command,
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no local shell
                arguments,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds + 5,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            return CheckResult(
                name,
                "timeout",
                124,
                _bounded(_text_from_timeout(exc.stdout)),
                _bounded(_text_from_timeout(exc.stderr) or "SSH check timed out"),
                duration_ms,
            )
        except OSError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            return CheckResult(
                name,
                "error",
                127,
                "",
                f"{type(exc).__name__}: {exc}",
                duration_ms,
            )

        duration_ms = round((time.monotonic() - started) * 1000)
        status = "pass" if completed.returncode == 0 else "error"
        return CheckResult(
            name,
            status,
            completed.returncode,
            _bounded(completed.stdout),
            _bounded(completed.stderr),
            duration_ms,
        )


def _docker_environment(config: DiagnosticConfig) -> str:
    socket = f"unix:///Users/julia/.colima/{config.colima_profile}/docker.sock"
    return f"PATH={REMOTE_PATH} DOCKER_HOST={socket}"


def build_base_checks(config: DiagnosticConfig) -> tuple[CheckSpec, ...]:
    """Return host and Docker checks that cannot mutate the runtime."""

    environment = _docker_environment(config)
    return (
        CheckSpec("host_time", "date -u '+%Y-%m-%dT%H:%M:%SZ'"),
        CheckSpec("host_memory", "sysctl -n hw.memsize; sysctl vm.swapusage"),
        CheckSpec(
            "colima_status",
            f"PATH={REMOTE_PATH} colima status --profile {config.colima_profile}",
        ),
        CheckSpec(
            "docker_info",
            environment
            + " docker info --format "
            + "'MemTotal={{.MemTotal}} DockerRootDir={{.DockerRootDir}} "
            + "LoggingDriver={{.LoggingDriver}} Driver={{.Driver}}'",
        ),
        CheckSpec(
            "kind_node",
            environment
            + " docker ps --filter 'name=control-plane' --format '{{.Names}}' "
            + "| head -n 1",
        ),
    )


def build_guest_checks(config: DiagnosticConfig, node_name: str) -> tuple[CheckSpec, ...]:
    """Return read-only checks for a validated kind node container."""

    if not SAFE_IDENTIFIER.fullmatch(node_name):
        raise ValueError(f"unsafe kind node: {node_name!r}")
    prefix = f"{_docker_environment(config)} docker exec {node_name}"
    return (
        CheckSpec("guest_time", f"{prefix} date -u +%s"),
        CheckSpec("guest_uptime", f"{prefix} cat /proc/uptime"),
        CheckSpec(
            "guest_memory",
            f"{prefix} grep -E "
            + "'^(MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback):' "
            + "/proc/meminfo",
        ),
        CheckSpec(
            "guest_pressure",
            f"{prefix} sh -c 'cat /proc/pressure/memory /proc/pressure/io'",
        ),
        CheckSpec("guest_disk", f"{prefix} df -h / /var/lib/containerd"),
        CheckSpec("containerd_active", f"{prefix} systemctl is-active containerd"),
        CheckSpec(
            "containerd_metadata",
            f"{prefix} systemctl show containerd -p ActiveEnterTimestamp -p NRestarts "
            + "--no-pager",
        ),
    )


def _result_dict(result: CheckResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "status": result.status,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
    }


def collect_diagnostics(
    config: DiagnosticConfig,
    client: ReadOnlySshClient,
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Collect every independent check and preserve failures as partial evidence."""

    results = [client.run(spec.name, spec.command) for spec in build_base_checks(config)]
    node_result = next(result for result in results if result.name == "kind_node")
    node_name = node_result.stdout.strip().splitlines()[0] if node_result.stdout.strip() else ""

    if node_result.status == "pass" and node_name:
        try:
            guest_checks = build_guest_checks(config, node_name)
        except ValueError as exc:
            results.append(CheckResult("guest_checks", "error", 2, "", str(exc), 0))
        else:
            results.extend(client.run(spec.name, spec.command) for spec in guest_checks)
    else:
        results.append(
            CheckResult(
                "guest_checks",
                "error",
                2,
                "",
                "kind node was not discovered; guest checks were not run",
                0,
            )
        )

    status = "complete" if all(result.status == "pass" for result in results) else "partial"
    capture_time = captured_at or datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    return {
        "status": status,
        "captured_at": capture_time,
        "ssh_host": config.ssh_host,
        "colima_profile": config.colima_profile,
        "timeout_seconds": config.timeout_seconds,
        "checks": [_result_dict(result) for result in results],
    }


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default="deproject-mac")
    parser.add_argument("--colima-profile", default="agentflow-fc5-7113966")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--ssh-executable", default="ssh")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = DiagnosticConfig(
            ssh_host=args.ssh_host,
            colima_profile=args.colima_profile,
            timeout_seconds=args.timeout_seconds,
        )
        client = ReadOnlySshClient(
            host=config.ssh_host,
            timeout_seconds=config.timeout_seconds,
            executable=args.ssh_executable,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    payload = collect_diagnostics(config, client)
    if args.output:
        _write_output(args.output, payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
