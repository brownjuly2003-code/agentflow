#!/usr/bin/env python3
"""Fail-closed recovery gate for the current ClickHouse and Iceberg stack.

The default CLI mode performs read-only preflight checks. Live recovery needs
both ``--execute`` and the exact acknowledgement token printed by ``--help``.
The recovery path starts existing Compose containers only; it never creates,
recreates, removes, or deletes containers or volumes.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any, NamedTuple

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
REMOTE_PATH = "/Users/julia/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
MAX_CAPTURE_CHARS = 32_768

CLICKHOUSE_CONTAINER = "agentflow-ch-rv-20260802-01"
CLICKHOUSE_VOLUME = "agentflow-ch-rv-20260802-01-data"
CLICKHOUSE_DATA_PATH = "/var/lib/clickhouse"
EXECUTION_ACK = "COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP"
DEFAULT_CLICKHOUSE_COMPOSE_FILE = "/tmp/agentflow-chk-restore-rv-20260802-01/clickhouse-compose.yml"  # noqa: S108
DEFAULT_ICEBERG_COMPOSE_FILE = (
    "/tmp/agentflow-iceberg-ed03fc47-20260801-01/docker-compose.iceberg.yml"  # noqa: S108
)

EXPECTED_IMAGES = {
    "clickhouse": "clickhouse/clickhouse-server:24.8",
    "minio": "minio/minio:RELEASE.2025-09-07T16-13-09Z",
    "minio-init": "minio/mc:RELEASE.2025-08-13T08-35-41Z",
    "iceberg-rest": "tabulario/iceberg-rest:0.6.0",
}

CLICKHOUSE_SERVICES = {"clickhouse"}
ICEBERG_SERVICES = {"minio", "minio-init", "iceberg-rest"}


class RecoveryError(RuntimeError):
    """A failed precondition, dependency gate, or scoped rollback."""


class RecoveryConfig:
    """Validated identifiers and bounds for one exact recovery target."""

    __slots__ = (
        "ssh_host",
        "colima_profile",
        "kind_node",
        "clickhouse_project",
        "clickhouse_compose_file",
        "iceberg_project",
        "iceberg_compose_file",
        "timeout_seconds",
    )

    def __init__(
        self,
        *,
        ssh_host: str,
        colima_profile: str,
        kind_node: str,
        clickhouse_project: str,
        clickhouse_compose_file: str,
        iceberg_project: str,
        iceberg_compose_file: str,
        timeout_seconds: int,
    ) -> None:
        if not SAFE_SSH_HOST.fullmatch(ssh_host):
            raise ValueError(f"unsafe SSH host: {ssh_host!r}")
        for label, value in (
            ("colima profile", colima_profile),
            ("kind node", kind_node),
            ("ClickHouse project", clickhouse_project),
            ("Iceberg project", iceberg_project),
        ):
            if not SAFE_IDENTIFIER.fullmatch(value):
                raise ValueError(f"unsafe {label}: {value!r}")
        _validate_remote_path("ClickHouse Compose file", clickhouse_compose_file)
        _validate_remote_path("Iceberg Compose file", iceberg_compose_file)
        if not 5 <= timeout_seconds <= 300:
            raise ValueError("timeout must be between 5 and 300 seconds")

        self.ssh_host = ssh_host
        self.colima_profile = colima_profile
        self.kind_node = kind_node
        self.clickhouse_project = clickhouse_project
        self.clickhouse_compose_file = clickhouse_compose_file
        self.iceberg_project = iceberg_project
        self.iceberg_compose_file = iceberg_compose_file
        self.timeout_seconds = timeout_seconds


class ContainerSpec(NamedTuple):
    name: str
    project: str
    service: str
    compose_file: str
    image: str


class ServiceRef(NamedTuple):
    project: str
    compose_file: str
    service: str


def _validate_remote_path(label: str, value: str) -> None:
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"unsafe {label}: {value!r}")
    if not PurePosixPath(value).is_absolute():
        raise ValueError(f"{label} must be an absolute POSIX path")


def _bounded(value: str) -> str:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value
    return value[:MAX_CAPTURE_CHARS] + "\n[output truncated]\n"


class SshDockerRunner:
    """Run one bounded Docker command against the exact Colima socket."""

    def __init__(
        self,
        *,
        host: str,
        colima_profile: str,
        ssh_executable: str = "ssh",
        docker_executable: str = "/usr/local/bin/docker",
    ) -> None:
        if not SAFE_SSH_HOST.fullmatch(host):
            raise ValueError(f"unsafe SSH host: {host!r}")
        if not SAFE_IDENTIFIER.fullmatch(colima_profile):
            raise ValueError(f"unsafe colima profile: {colima_profile!r}")
        _validate_remote_path("Docker executable", docker_executable)
        self._host = host
        self._colima_profile = colima_profile
        self._ssh_executable = ssh_executable
        self._docker_executable = docker_executable

    def run(self, arguments: Sequence[str], *, timeout_seconds: int) -> str:
        socket = f"unix:///Users/julia/.colima/{self._colima_profile}/docker.sock"
        remote_arguments = [
            "env",
            f"PATH={REMOTE_PATH}",
            f"DOCKER_HOST={socket}",
            self._docker_executable,
            *arguments,
        ]
        connect_timeout = min(timeout_seconds, 10)
        command = [
            self._ssh_executable,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=1",
            self._host,
            shlex.join(remote_arguments),
        ]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no local shell
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds + 5,
            )
        except subprocess.TimeoutExpired as error:
            raise RecoveryError("remote Docker command timed out") from error
        except OSError as error:
            raise RecoveryError(f"could not run remote Docker command: {error}") from error

        if completed.returncode != 0:
            detail = _bounded(completed.stderr.strip() or completed.stdout.strip())
            raise RecoveryError(f"remote Docker command failed: {detail}")
        return _bounded(completed.stdout)


class DockerBackend:
    """Docker operations used by the recovery state machine."""

    def __init__(self, runner: Any, *, timeout_seconds: int) -> None:
        self._runner = runner
        self._timeout_seconds = timeout_seconds

    def _compose(self, project: str, compose_file: str, *arguments: str) -> str:
        return self._runner.run(
            [
                "compose",
                "--project-name",
                project,
                "--file",
                compose_file,
                *arguments,
            ],
            timeout_seconds=self._timeout_seconds,
        )

    def compose_services(self, project: str, compose_file: str) -> list[str]:
        output = self._compose(project, compose_file, "config", "--services")
        services = [line.strip() for line in output.splitlines() if line.strip()]
        if not services:
            raise RecoveryError(f"Compose project {project} returned no services")
        return services

    def inspect_container(self, name: str) -> dict[str, object]:
        output = self._runner.run(
            ["inspect", name],
            timeout_seconds=self._timeout_seconds,
        )
        payload = _single_inspect_object(output, f"container {name}")
        config = _mapping(payload.get("Config"), f"container {name} Config")
        host_config = _mapping(payload.get("HostConfig"), f"container {name} HostConfig")
        state = _mapping(payload.get("State"), f"container {name} State")
        labels = config.get("Labels") or {}
        if not isinstance(labels, dict):
            raise RecoveryError(f"container {name} labels are invalid")
        restart_policy = _mapping(
            host_config.get("RestartPolicy"),
            f"container {name} restart policy",
        )
        health_payload = state.get("Health")
        health = None
        if health_payload is not None:
            health = _mapping(health_payload, f"container {name} health").get("Status")

        mounts_payload = payload.get("Mounts") or []
        if not isinstance(mounts_payload, list):
            raise RecoveryError(f"container {name} mounts are invalid")
        mounts: list[dict[str, str]] = []
        for mount in mounts_payload:
            if not isinstance(mount, dict):
                raise RecoveryError(f"container {name} mount entry is invalid")
            mounts.append(
                {
                    "type": str(mount.get("Type", "")),
                    "name": str(mount.get("Name", "")),
                    "destination": str(mount.get("Destination", "")),
                }
            )

        compose_files_label = labels.get("com.docker.compose.project.config_files", "")
        compose_files = [
            value.strip() for value in str(compose_files_label).split(",") if value.strip()
        ]
        return {
            "name": str(payload.get("Name", "")).lstrip("/"),
            "project": str(labels.get("com.docker.compose.project", "")),
            "service": str(labels.get("com.docker.compose.service", "")),
            "compose_files": compose_files,
            "image": str(config.get("Image", "")),
            "status": str(state.get("Status", "")),
            "health": None if health is None else str(health),
            "exit_code": int(state.get("ExitCode", -1)),
            "restart_policy": str(restart_policy.get("Name", "")),
            "mounts": mounts,
        }

    def inspect_volume(self, name: str) -> dict[str, str]:
        output = self._runner.run(
            ["volume", "inspect", name],
            timeout_seconds=self._timeout_seconds,
        )
        payload = _single_inspect_object(output, f"volume {name}")
        return {"name": str(payload.get("Name", ""))}

    def start_service(self, project: str, compose_file: str, service: str) -> None:
        self._compose(project, compose_file, "start", service)

    def stop_service(self, project: str, compose_file: str, service: str) -> None:
        self._compose(
            project,
            compose_file,
            "stop",
            "--timeout",
            str(self._timeout_seconds),
            service,
        )

    def wait_healthy(self, name: str, timeout_seconds: int) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self.inspect_container(name)
            status = state["status"]
            health = state["health"]
            if status == "running" and health == "healthy":
                return state
            if status in {"dead", "exited", "removing"}:
                raise RecoveryError(f"container {name} stopped before becoming healthy")
            if health == "unhealthy":
                raise RecoveryError(f"container {name} became unhealthy")
            if time.monotonic() >= deadline:
                raise RecoveryError(f"container {name} health gate timed out")
            time.sleep(2)

    def wait_running(self, name: str, timeout_seconds: int) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self.inspect_container(name)
            status = state["status"]
            if status == "running":
                return state
            if status in {"dead", "exited", "removing"}:
                raise RecoveryError(f"container {name} stopped before becoming ready")
            if time.monotonic() >= deadline:
                raise RecoveryError(f"container {name} running gate timed out")
            time.sleep(2)

    def wait_exited_zero(self, name: str, timeout_seconds: int) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self.inspect_container(name)
            status = state["status"]
            if status == "exited":
                if state["exit_code"] != 0:
                    raise RecoveryError(
                        f"one-shot container {name} exited with code {state['exit_code']}"
                    )
                return state
            if status == "dead":
                raise RecoveryError(f"one-shot container {name} entered dead state")
            if time.monotonic() >= deadline:
                raise RecoveryError(f"one-shot container {name} completion gate timed out")
            time.sleep(2)

    def probe_from_kind(self, kind_node: str, url: str) -> str:
        return self._runner.run(
            [
                "exec",
                kind_node,
                "/usr/bin/curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "5",
                url,
            ],
            timeout_seconds=self._timeout_seconds,
        )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecoveryError(f"{label} is not an object")
    return value


def _single_inspect_object(output: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise RecoveryError(f"{label} inspect output is not valid JSON") from error
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RecoveryError(f"{label} inspect output must contain exactly one object")
    return payload[0]


def _container_specs(config: RecoveryConfig) -> tuple[ContainerSpec, ...]:
    return (
        ContainerSpec(
            CLICKHOUSE_CONTAINER,
            config.clickhouse_project,
            "clickhouse",
            config.clickhouse_compose_file,
            EXPECTED_IMAGES["clickhouse"],
        ),
        ContainerSpec(
            f"{config.iceberg_project}-minio-1",
            config.iceberg_project,
            "minio",
            config.iceberg_compose_file,
            EXPECTED_IMAGES["minio"],
        ),
        ContainerSpec(
            f"{config.iceberg_project}-minio-init-1",
            config.iceberg_project,
            "minio-init",
            config.iceberg_compose_file,
            EXPECTED_IMAGES["minio-init"],
        ),
        ContainerSpec(
            f"{config.iceberg_project}-iceberg-rest-1",
            config.iceberg_project,
            "iceberg-rest",
            config.iceberg_compose_file,
            EXPECTED_IMAGES["iceberg-rest"],
        ),
    )


def _require_exact_services(actual: Sequence[str], expected: set[str], project: str) -> None:
    actual_set = set(actual)
    if len(actual) != len(actual_set) or actual_set != expected:
        raise RecoveryError(
            f"Compose services for {project} changed: expected {sorted(expected)}, "
            f"got {sorted(actual_set)}"
        )


def _validate_container(spec: ContainerSpec, state: dict[str, object]) -> None:
    for field, expected in (
        ("name", spec.name),
        ("project", spec.project),
        ("service", spec.service),
        ("image", spec.image),
        ("restart_policy", "no"),
    ):
        if state.get(field) != expected:
            raise RecoveryError(
                f"container {spec.name} {field} changed: "
                f"expected {expected!r}, got {state.get(field)!r}"
            )

    compose_files = state.get("compose_files")
    if not isinstance(compose_files, list) or spec.compose_file not in compose_files:
        raise RecoveryError(
            f"container {spec.name} is not owned by Compose file {spec.compose_file}"
        )

    status = state.get("status")
    if spec.service == "minio-init":
        if status != "exited" or state.get("exit_code") != 0:
            raise RecoveryError("minio-init must be a previously successful exited one-shot")
        return
    if status not in {"exited", "running"}:
        raise RecoveryError(f"container {spec.name} has unsafe state {status!r}")
    if status == "running" and spec.service in {"clickhouse", "minio"}:
        if state.get("health") != "healthy":
            raise RecoveryError(f"pre-existing container {spec.name} is not healthy")


def preflight_recovery(
    config: RecoveryConfig,
    backend: Any,
) -> dict[str, dict[str, object]]:
    """Validate exact owners and persistence before any start/stop operation."""
    _require_exact_services(
        backend.compose_services(
            config.clickhouse_project,
            config.clickhouse_compose_file,
        ),
        CLICKHOUSE_SERVICES,
        config.clickhouse_project,
    )
    _require_exact_services(
        backend.compose_services(
            config.iceberg_project,
            config.iceberg_compose_file,
        ),
        ICEBERG_SERVICES,
        config.iceberg_project,
    )

    volume = backend.inspect_volume(CLICKHOUSE_VOLUME)
    if volume.get("name") != CLICKHOUSE_VOLUME:
        raise RecoveryError(f"volume {CLICKHOUSE_VOLUME} identity changed")

    states: dict[str, dict[str, object]] = {}
    for spec in _container_specs(config):
        state = backend.inspect_container(spec.name)
        _validate_container(spec, state)
        states[spec.service] = state

    clickhouse_mounts = states["clickhouse"].get("mounts")
    expected_mount = {
        "type": "volume",
        "name": CLICKHOUSE_VOLUME,
        "destination": CLICKHOUSE_DATA_PATH,
    }
    if not isinstance(clickhouse_mounts, list) or expected_mount not in clickhouse_mounts:
        raise RecoveryError(
            f"container {CLICKHOUSE_CONTAINER} does not mount {CLICKHOUSE_VOLUME} "
            f"at {CLICKHOUSE_DATA_PATH}"
        )

    kind_state = backend.inspect_container(config.kind_node)
    if kind_state.get("name") != config.kind_node or kind_state.get("status") != "running":
        raise RecoveryError(f"kind node {config.kind_node} is not running")
    return states


def _start_if_exited(
    backend: Any,
    state: dict[str, object],
    service: ServiceRef,
    started: list[ServiceRef],
) -> None:
    if state["status"] == "running":
        return
    started.append(service)
    backend.start_service(service.project, service.compose_file, service.service)


def _rollback_started(backend: Any, started: Sequence[ServiceRef]) -> list[str]:
    errors: list[str] = []
    for service in reversed(started):
        try:
            backend.stop_service(service.project, service.compose_file, service.service)
        except RecoveryError as error:
            errors.append(f"{service.project}/{service.service}: {error}")
    return errors


def recover_dependencies(config: RecoveryConfig, backend: Any) -> dict[str, object]:
    """Start existing dependency containers, gate health, and roll back on failure."""
    states = preflight_recovery(config, backend)
    clickhouse = ServiceRef(
        config.clickhouse_project,
        config.clickhouse_compose_file,
        "clickhouse",
    )
    minio = ServiceRef(config.iceberg_project, config.iceberg_compose_file, "minio")
    minio_init = ServiceRef(
        config.iceberg_project,
        config.iceberg_compose_file,
        "minio-init",
    )
    iceberg_rest = ServiceRef(
        config.iceberg_project,
        config.iceberg_compose_file,
        "iceberg-rest",
    )
    started: list[ServiceRef] = []

    try:
        _start_if_exited(backend, states["clickhouse"], clickhouse, started)
        backend.wait_healthy(CLICKHOUSE_CONTAINER, config.timeout_seconds)

        _start_if_exited(backend, states["minio"], minio, started)
        minio_name = f"{config.iceberg_project}-minio-1"
        backend.wait_healthy(minio_name, config.timeout_seconds)

        if states["iceberg-rest"]["status"] == "exited":
            started.append(minio_init)
            backend.start_service(
                minio_init.project,
                minio_init.compose_file,
                minio_init.service,
            )
            backend.wait_exited_zero(
                f"{config.iceberg_project}-minio-init-1",
                config.timeout_seconds,
            )
            started.remove(minio_init)

        _start_if_exited(backend, states["iceberg-rest"], iceberg_rest, started)
        iceberg_name = f"{config.iceberg_project}-iceberg-rest-1"
        backend.wait_running(iceberg_name, config.timeout_seconds)

        clickhouse_probe = backend.probe_from_kind(
            config.kind_node,
            "http://172.18.0.1:8123/ping",
        )
        if clickhouse_probe.strip() != "Ok.":
            raise RecoveryError("ClickHouse kind-network probe returned unexpected content")
        backend.probe_from_kind(
            config.kind_node,
            "http://172.18.0.1:9000/minio/health/live",
        )
        iceberg_probe = backend.probe_from_kind(
            config.kind_node,
            "http://172.18.0.1:8181/v1/config",
        )
        try:
            iceberg_payload = json.loads(iceberg_probe)
        except json.JSONDecodeError as error:
            raise RecoveryError("Iceberg REST probe returned invalid JSON") from error
        if not isinstance(iceberg_payload, dict):
            raise RecoveryError("Iceberg REST probe returned a non-object payload")
    except RecoveryError as error:
        rollback_errors = _rollback_started(backend, started)
        if rollback_errors:
            detail = "; ".join(rollback_errors)
            raise RecoveryError(f"{error}; rollback failures: {detail}") from error
        raise

    return {
        "status": "ready",
        "ready_for_workload_verification": True,
        "started_services": [f"{service.project}/{service.service}" for service in started],
        "gates": {
            "clickhouse": "healthy_and_kind_reachable",
            "minio": "healthy_and_kind_reachable",
            "minio_init": "exited_0",
            "iceberg_rest": "running_and_kind_reachable",
        },
        "data_preservation": {
            "clickhouse": f"existing_named_volume:{CLICKHOUSE_VOLUME}",
            "minio": "existing_container_writable_layer",
        },
        "rollback": "stop_only_services_started_by_this_gate; no_remove; no_volume_delete",
    }


def _preflight_payload(
    config: RecoveryConfig,
    states: dict[str, dict[str, object]],
) -> dict[str, object]:
    return {
        "status": "preflight_passed",
        "ready_for_workload_verification": False,
        "execute": False,
        "services": {
            service: {
                "name": state["name"],
                "status": state["status"],
                "health": state.get("health"),
                "exit_code": state["exit_code"],
            }
            for service, state in states.items()
        },
        "kind_node": config.kind_node,
        "next_action": (f"rerun with --execute --acknowledge-live-recovery {EXECUTION_ACK}"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default="deproject-mac")
    parser.add_argument("--colima-profile", default="agentflow-fc5-7113966")
    parser.add_argument("--kind-node", default="agentflow-reverify-ed03fc47-control-plane")
    parser.add_argument(
        "--clickhouse-project",
        default="agentflow-ch-rv-20260802-01",
    )
    parser.add_argument(
        "--clickhouse-compose-file",
        default=DEFAULT_CLICKHOUSE_COMPOSE_FILE,
    )
    parser.add_argument(
        "--iceberg-project",
        default="agentflow-iceberg-rv-20260802-01",
    )
    parser.add_argument(
        "--iceberg-compose-file",
        default=DEFAULT_ICEBERG_COMPOSE_FILE,
    )
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="start existing containers after preflight (never create or recreate)",
    )
    parser.add_argument(
        "--acknowledge-live-recovery",
        metavar="TOKEN",
        help=f"required with --execute; exact value: {EXECUTION_ACK}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.execute and arguments.acknowledge_live_recovery != EXECUTION_ACK:
        print(
            f"error: --execute requires --acknowledge-live-recovery {EXECUTION_ACK}",
            file=sys.stderr,
        )
        return 2
    if not arguments.execute and arguments.acknowledge_live_recovery is not None:
        print("error: acknowledgement is only valid with --execute", file=sys.stderr)
        return 2

    try:
        config = RecoveryConfig(
            ssh_host=arguments.ssh_host,
            colima_profile=arguments.colima_profile,
            kind_node=arguments.kind_node,
            clickhouse_project=arguments.clickhouse_project,
            clickhouse_compose_file=arguments.clickhouse_compose_file,
            iceberg_project=arguments.iceberg_project,
            iceberg_compose_file=arguments.iceberg_compose_file,
            timeout_seconds=arguments.timeout_seconds,
        )
        runner = SshDockerRunner(
            host=config.ssh_host,
            colima_profile=config.colima_profile,
        )
        backend = DockerBackend(runner, timeout_seconds=config.timeout_seconds)
        if arguments.execute:
            result = recover_dependencies(config, backend)
        else:
            result = _preflight_payload(config, preflight_recovery(config, backend))
    except (RecoveryError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
