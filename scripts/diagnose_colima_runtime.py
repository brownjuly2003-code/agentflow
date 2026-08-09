#!/usr/bin/env python3
"""Collect bounded, read-only Colima and kind runtime diagnostics over SSH."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
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


def _precise_clock_command(prefix: str) -> str:
    host_time_ns = f"PATH={REMOTE_PATH} python3 -c 'import time; print(time.time_ns())'"
    return (
        f"host_before_ns=$({host_time_ns}); "
        + f"guest_ns=$({prefix} date -u +%s%N); "
        + f"host_after_ns=$({host_time_ns}); "
        + "host_midpoint_ns=$(((host_before_ns + host_after_ns) / 2)); "
        + "offset_ns=$((guest_ns - host_midpoint_ns)); "
        + "round_trip_ns=$((host_after_ns - host_before_ns)); "
        + "printf 'host_before_ns=%s guest_ns=%s host_after_ns=%s "
        + "offset_ns=%s round_trip_ns=%s\\n' "
        + '"$host_before_ns" "$guest_ns" "$host_after_ns" '
        + '"$offset_ns" "$round_trip_ns"'
    )


def _container_io_inventory_command(prefix: str) -> str:
    script = """\
set -eu
cgroup_fs=$(stat -fc %T /sys/fs/cgroup)
container_ids=$(crictl ps -q | sort)
[ -n "$container_ids" ] || { printf 'no running CRI containers\\n' >&2; exit 2; }
pid_and_name_template='{{.info.pid}} {{.status.metadata.name}}'
pod_template='{{index .status.labels "io.kubernetes.pod.name"}}'
inspect_template="$pid_and_name_template $pod_template"
output_format='container_id=%s\\tpod=%s\\tcontainer=%s\\t'
output_format="$output_format"'cgroup_mode=%s\\tread_bytes=%s\\twrite_bytes=%s\\t'
output_format="$output_format"'read_ios=%s\\twrite_ios=%s\\n'
for container_id in $container_ids; do
  details=$(crictl inspect -o go-template --template "$inspect_template" "$container_id")
  set -- $details
  if [ "$#" -ne 3 ]; then
    printf 'invalid inspect metadata for %s\\n' "$container_id" >&2
    exit 2
  fi
  proc_id=$1
  container_name=$2
  pod_name=$3
  case "$proc_id" in
    ''|*[!0-9]*) printf 'invalid runtime pid for %s\\n' "$container_id" >&2; exit 2 ;;
  esac
  if [ ! -r "/proc/$proc_id/cgroup" ]; then
    printf 'missing cgroup for %s\\n' "$container_id" >&2
    exit 2
  fi
  case "$cgroup_fs" in
    cgroup2fs)
      cgroup_mode=v2
      cgroup_path=$(awk -F: '$1 == "0" { print $3; exit }' "/proc/$proc_id/cgroup")
      io_path="/sys/fs/cgroup${cgroup_path}/io.stat"
      if [ ! -r "$io_path" ]; then
        printf 'missing v2 io.stat for %s\\n' "$container_id" >&2
        exit 2
      fi
      set -- $(awk '{
        for (field = 2; field <= NF; field++) {
          split($field, pair, "=")
          if (pair[1] == "rbytes") read_bytes += pair[2]
          else if (pair[1] == "wbytes") write_bytes += pair[2]
          else if (pair[1] == "rios") read_ios += pair[2]
          else if (pair[1] == "wios") write_ios += pair[2]
        }
      } END {
        printf "%.0f %.0f %.0f %.0f\\n", read_bytes, write_bytes, read_ios, write_ios
      }' "$io_path")
      read_bytes=$1
      write_bytes=$2
      read_ios=$3
      write_ios=$4
      ;;
    tmpfs)
      cgroup_mode=v1
      cgroup_path=$(awk -F: '$2 ~ /(^|,)blkio(,|$)/ { print $3; exit }' "/proc/$proc_id/cgroup")
      bytes_path="/sys/fs/cgroup/blkio${cgroup_path}/blkio.throttle.io_service_bytes_recursive"
      ios_path="/sys/fs/cgroup/blkio${cgroup_path}/blkio.throttle.io_serviced_recursive"
      if [ ! -r "$bytes_path" ] || [ ! -r "$ios_path" ]; then
        bytes_path="/sys/fs/cgroup/blkio${cgroup_path}/blkio.io_service_bytes_recursive"
        ios_path="/sys/fs/cgroup/blkio${cgroup_path}/blkio.io_serviced_recursive"
      fi
      if [ ! -r "$bytes_path" ] || [ ! -r "$ios_path" ]; then
        printf 'missing v1 blkio counters for %s\\n' "$container_id" >&2
        exit 2
      fi
      read_bytes=$(awk '
        $2 == "Read" { total += $3 }
        END { printf "%.0f\\n", total + 0 }
      ' "$bytes_path")
      write_bytes=$(awk '
        $2 == "Write" { total += $3 }
        END { printf "%.0f\\n", total + 0 }
      ' "$bytes_path")
      read_ios=$(awk '
        $2 == "Read" { total += $3 }
        END { printf "%.0f\\n", total + 0 }
      ' "$ios_path")
      write_ios=$(awk '
        $2 == "Write" { total += $3 }
        END { printf "%.0f\\n", total + 0 }
      ' "$ios_path")
      ;;
    *) printf 'unsupported cgroup filesystem: %s\\n' "$cgroup_fs" >&2; exit 2 ;;
  esac
  printf "$output_format" \
    "$container_id" "$pod_name" "$container_name" "$cgroup_mode" \
    "$read_bytes" "$write_bytes" "$read_ios" "$write_ios"
done
"""
    return f"{prefix} sh -c {shlex.quote(script)}"


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
    journal = f"{prefix} journalctl -b --since '48 hours ago' --no-pager -o short-iso"
    return (
        CheckSpec("guest_time", f"{prefix} date -u +%s"),
        CheckSpec("clock_pair", _precise_clock_command(prefix)),
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
        CheckSpec("container_io_inventory", _container_io_inventory_command(prefix)),
        CheckSpec(
            "clock_jumps",
            f"{journal} | grep -F 'Time jumped backwards' | tail -n 100",
        ),
        CheckSpec(
            "kernel_stalls",
            f"{prefix} journalctl -k -b --since '48 hours ago' --no-pager "
            + "-o short-iso | grep -E -i "
            + "'blocked for more than|I/O error|oom|out of memory|overlay.*"
            + "(sync|writeback|stall)' | tail -n 100",
        ),
        CheckSpec(
            "containerd_errors",
            f"{prefix} journalctl -u containerd -b --since '48 hours ago' --no-pager "
            + "-o short-iso | grep -E -i "
            + "'error|timeout|deadline|blocked|failed' | tail -n 100",
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
