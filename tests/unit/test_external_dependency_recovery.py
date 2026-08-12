"""Contract tests for the fail-closed external dependency recovery gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "recover_external_dependencies.py"


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing recovery gate at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "recover_external_dependencies_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(module):
    return module.RecoveryConfig(
        ssh_host="deproject-mac",
        colima_profile="agentflow-fc5-7113966",
        kind_node="agentflow-reverify-ed03fc47-control-plane",
        clickhouse_project="agentflow-ch-rv-20260802-01",
        clickhouse_compose_file=module.DEFAULT_CLICKHOUSE_COMPOSE_FILE,
        iceberg_project="agentflow-iceberg-rv-20260802-01",
        iceberg_compose_file=module.DEFAULT_ICEBERG_COMPOSE_FILE,
        timeout_seconds=30,
    )


def _container(
    *,
    name: str,
    project: str,
    service: str,
    compose_file: str,
    image: str,
    status: str = "exited",
    health: str | None = None,
    exit_code: int = 0,
    mounts: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "project": project,
        "service": service,
        "compose_files": [compose_file],
        "image": image,
        "status": status,
        "health": health,
        "exit_code": exit_code,
        "restart_policy": "no",
        "mounts": mounts or [],
    }


class FakeBackend:
    def __init__(self, module, config) -> None:
        self.module = module
        self.config = config
        self.events: list[tuple[object, ...]] = []
        self.fail_init = False
        self.fail_probe_url: str | None = None
        self.volume: dict[str, str] | None = {
            "name": module.CLICKHOUSE_VOLUME,
        }
        self.services = {
            (config.clickhouse_project, config.clickhouse_compose_file): ["clickhouse"],
            (config.iceberg_project, config.iceberg_compose_file): [
                "minio",
                "minio-init",
                "iceberg-rest",
            ],
        }
        self.states = {
            module.CLICKHOUSE_CONTAINER: _container(
                name=module.CLICKHOUSE_CONTAINER,
                project=config.clickhouse_project,
                service="clickhouse",
                compose_file=config.clickhouse_compose_file,
                image=module.EXPECTED_IMAGES["clickhouse"],
                exit_code=137,
                mounts=[
                    {
                        "type": "volume",
                        "name": module.CLICKHOUSE_VOLUME,
                        "destination": "/var/lib/clickhouse",
                    }
                ],
            ),
            f"{config.iceberg_project}-minio-1": _container(
                name=f"{config.iceberg_project}-minio-1",
                project=config.iceberg_project,
                service="minio",
                compose_file=config.iceberg_compose_file,
                image=module.EXPECTED_IMAGES["minio"],
            ),
            f"{config.iceberg_project}-minio-init-1": _container(
                name=f"{config.iceberg_project}-minio-init-1",
                project=config.iceberg_project,
                service="minio-init",
                compose_file=config.iceberg_compose_file,
                image=module.EXPECTED_IMAGES["minio-init"],
            ),
            f"{config.iceberg_project}-iceberg-rest-1": _container(
                name=f"{config.iceberg_project}-iceberg-rest-1",
                project=config.iceberg_project,
                service="iceberg-rest",
                compose_file=config.iceberg_compose_file,
                image=module.EXPECTED_IMAGES["iceberg-rest"],
                exit_code=137,
            ),
            config.kind_node: {
                "name": config.kind_node,
                "status": "running",
            },
        }

    def compose_services(self, project: str, compose_file: str) -> list[str]:
        self.events.append(("compose_services", project, compose_file))
        return self.services[(project, compose_file)]

    def inspect_container(self, name: str) -> dict[str, object]:
        self.events.append(("inspect_container", name))
        state = self.states.get(name)
        if state is None:
            raise self.module.RecoveryError(f"container {name} is missing")
        return dict(state)

    def inspect_volume(self, name: str) -> dict[str, str]:
        self.events.append(("inspect_volume", name))
        if self.volume is None:
            raise self.module.RecoveryError(f"volume {name} is missing")
        return dict(self.volume)

    def start_service(self, project: str, compose_file: str, service: str) -> None:
        self.events.append(("start", project, service))
        container_name = self._service_container(project, service)
        self.states[container_name]["status"] = "running"
        self.states[container_name]["health"] = "starting"

    def stop_service(self, project: str, compose_file: str, service: str) -> None:
        self.events.append(("stop", project, service))
        container_name = self._service_container(project, service)
        self.states[container_name]["status"] = "exited"

    def wait_healthy(self, name: str, timeout_seconds: int) -> dict[str, object]:
        self.events.append(("wait_healthy", name, timeout_seconds))
        self.states[name]["status"] = "running"
        self.states[name]["health"] = "healthy"
        return dict(self.states[name])

    def wait_running(self, name: str, timeout_seconds: int) -> dict[str, object]:
        self.events.append(("wait_running", name, timeout_seconds))
        self.states[name]["status"] = "running"
        return dict(self.states[name])

    def wait_exited_zero(self, name: str, timeout_seconds: int) -> dict[str, object]:
        self.events.append(("wait_exited_zero", name, timeout_seconds))
        if self.fail_init:
            raise self.module.RecoveryError("minio-init exited with code 1")
        self.states[name]["status"] = "exited"
        self.states[name]["health"] = None
        self.states[name]["exit_code"] = 0
        return dict(self.states[name])

    def probe_from_kind(self, kind_node: str, url: str) -> str:
        self.events.append(("probe", kind_node, url))
        if url == self.fail_probe_url:
            raise self.module.RecoveryError(f"probe failed: {url}")
        if url.endswith("/ping"):
            return "Ok.\n"
        if url.endswith("/v1/config"):
            return '{"defaults":{}}\n'
        return "OK\n"

    def _service_container(self, project: str, service: str) -> str:
        if service == "clickhouse":
            return self.module.CLICKHOUSE_CONTAINER
        return f"{project}-{service}-1"


def test_recovery_orders_one_shot_and_requires_all_dependency_gates() -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)

    result = module.recover_dependencies(config, backend)

    assert result["status"] == "ready"
    assert result["ready_for_workload_verification"] is True
    actions = [event for event in backend.events if event[0] in {"start", "stop"}]
    assert actions == [
        ("start", config.clickhouse_project, "clickhouse"),
        ("start", config.iceberg_project, "minio"),
        ("start", config.iceberg_project, "minio-init"),
        ("start", config.iceberg_project, "iceberg-rest"),
    ]
    decisive_events = [
        event
        for event in backend.events
        if event[0] in {"wait_healthy", "wait_exited_zero", "wait_running", "probe"}
    ]
    assert decisive_events == [
        ("wait_healthy", module.CLICKHOUSE_CONTAINER, 30),
        ("wait_healthy", f"{config.iceberg_project}-minio-1", 30),
        ("wait_exited_zero", f"{config.iceberg_project}-minio-init-1", 30),
        ("wait_running", f"{config.iceberg_project}-iceberg-rest-1", 30),
        ("probe", config.kind_node, "http://172.18.0.1:8123/ping"),
        ("probe", config.kind_node, "http://172.18.0.1:9000/minio/health/live"),
        ("probe", config.kind_node, "http://172.18.0.1:8181/v1/config"),
    ]


def test_recovery_retries_transient_iceberg_connection_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    iceberg_url = "http://172.18.0.1:8181/v1/config"
    attempts = 0
    original_probe = backend.probe_from_kind

    def flaky_probe(kind_node: str, url: str) -> str:
        nonlocal attempts
        if url == iceberg_url:
            attempts += 1
            if attempts == 1:
                backend.events.append(("probe", kind_node, url))
                raise module.RecoveryError(
                    "remote Docker command failed: curl: (7) Failed to connect"
                )
        return original_probe(kind_node, url)

    backend.probe_from_kind = flaky_probe
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda seconds: backend.events.append(("sleep", seconds)),
    )

    result = module.recover_dependencies(config, backend)

    assert result["ready_for_workload_verification"] is True
    assert attempts == 2
    assert ("sleep", 2) in backend.events
    assert [
        event for event in backend.events if event[:1] == ("probe",) and event[2] == iceberg_url
    ] == [
        ("probe", config.kind_node, iceberg_url),
        ("probe", config.kind_node, iceberg_url),
    ]


def test_recovery_fails_when_iceberg_stops_during_readiness_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    iceberg_name = f"{config.iceberg_project}-iceberg-rest-1"
    iceberg_url = "http://172.18.0.1:8181/v1/config"
    original_probe = backend.probe_from_kind

    def stopped_probe(kind_node: str, url: str) -> str:
        if url != iceberg_url:
            return original_probe(kind_node, url)
        backend.events.append(("probe", kind_node, url))
        backend.states[iceberg_name]["status"] = "exited"
        backend.states[iceberg_name]["exit_code"] = 1
        raise module.RecoveryError("remote Docker command failed: curl: (7) Failed to connect")

    backend.probe_from_kind = stopped_probe
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda _seconds: pytest.fail("terminal state must not be retried"),
    )

    with pytest.raises(
        module.RecoveryError,
        match="stopped before endpoint became ready",
    ):
        module.recover_dependencies(config, backend)

    iceberg_probes = [
        event for event in backend.events if event[:1] == ("probe",) and event[2] == iceberg_url
    ]
    assert iceberg_probes == [("probe", config.kind_node, iceberg_url)]


def test_recovery_bounds_transient_iceberg_readiness_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    iceberg_url = "http://172.18.0.1:8181/v1/config"
    original_probe = backend.probe_from_kind
    monotonic_values = iter((100.0, 131.0))

    def refused_probe(kind_node: str, url: str) -> str:
        if url != iceberg_url:
            return original_probe(kind_node, url)
        backend.events.append(("probe", kind_node, url))
        raise module.RecoveryError("remote Docker command failed: curl: (7) Failed to connect")

    backend.probe_from_kind = refused_probe
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        module.RecoveryError,
        match="Iceberg REST endpoint readiness gate timed out",
    ):
        module.recover_dependencies(config, backend)

    iceberg_probes = [
        event for event in backend.events if event[:1] == ("probe",) and event[2] == iceberg_url
    ]
    assert iceberg_probes == [("probe", config.kind_node, iceberg_url)]


def test_recovery_does_not_retry_nontransient_iceberg_probe_error() -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    iceberg_url = "http://172.18.0.1:8181/v1/config"
    backend.fail_probe_url = iceberg_url

    with pytest.raises(module.RecoveryError, match="probe failed"):
        module.recover_dependencies(config, backend)

    iceberg_probes = [
        event for event in backend.events if event[:1] == ("probe",) and event[2] == iceberg_url
    ]
    assert iceberg_probes == [("probe", config.kind_node, iceberg_url)]


def test_missing_named_volume_fails_before_any_mutation() -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    backend.volume = None

    with pytest.raises(module.RecoveryError, match="volume .* is missing"):
        module.recover_dependencies(config, backend)

    assert not [event for event in backend.events if event[0] in {"start", "stop"}]


def test_failed_one_shot_stops_only_services_started_by_this_gate() -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    backend.fail_init = True

    with pytest.raises(module.RecoveryError, match="minio-init exited with code 1"):
        module.recover_dependencies(config, backend)

    assert ("start", config.iceberg_project, "iceberg-rest") not in backend.events
    stops = [event for event in backend.events if event[0] == "stop"]
    assert stops == [
        ("stop", config.iceberg_project, "minio-init"),
        ("stop", config.iceberg_project, "minio"),
        ("stop", config.clickhouse_project, "clickhouse"),
    ]


def test_rollback_leaves_preexisting_healthy_service_running() -> None:
    module = _load_module()
    config = _config(module)
    backend = FakeBackend(module, config)
    backend.states[module.CLICKHOUSE_CONTAINER].update(
        status="running",
        health="healthy",
        exit_code=0,
    )
    backend.fail_probe_url = "http://172.18.0.1:8181/v1/config"

    with pytest.raises(module.RecoveryError, match="probe failed"):
        module.recover_dependencies(config, backend)

    assert ("start", config.clickhouse_project, "clickhouse") not in backend.events
    stops = [event for event in backend.events if event[0] == "stop"]
    assert stops == [
        ("stop", config.iceberg_project, "iceberg-rest"),
        ("stop", config.iceberg_project, "minio"),
    ]


def test_docker_backend_uses_start_and_scoped_stop_without_recreate_or_delete() -> None:
    module = _load_module()

    class RecordingRunner:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def run(self, arguments, *, timeout_seconds: int) -> str:
            assert timeout_seconds == 30
            self.commands.append(tuple(arguments))
            return ""

    runner = RecordingRunner()
    backend = module.DockerBackend(runner, timeout_seconds=30)
    compose_file = "/opt/agentflow/recovery/docker-compose.yml"

    backend.start_service("agentflow-recovery", compose_file, "minio")
    backend.stop_service("agentflow-recovery", compose_file, "minio")

    assert runner.commands == [
        (
            "compose",
            "--project-name",
            "agentflow-recovery",
            "--file",
            compose_file,
            "start",
            "minio",
        ),
        (
            "compose",
            "--project-name",
            "agentflow-recovery",
            "--file",
            compose_file,
            "stop",
            "--timeout",
            "30",
            "minio",
        ),
    ]
    flattened = " ".join(part for command in runner.commands for part in command)
    assert " up " not in f" {flattened} "
    assert " down " not in f" {flattened} "
    assert " rm " not in f" {flattened} "
    assert " -v " not in f" {flattened} "
