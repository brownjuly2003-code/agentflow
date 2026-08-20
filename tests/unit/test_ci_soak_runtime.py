from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FOUNDATION_ROOT = PROJECT_ROOT / "scripts" / "golden_soak"
RUNTIME_PATH = FOUNDATION_ROOT / "runtime.py"
SHIM_PATH = FOUNDATION_ROOT / "pods_shim.py"

PROJECT_NAME = "agentflow-ci-soak-test"
RUN_LABEL = "golden-4h-soak-rv-20260819-07"
JOB_ID = "1" * 32
JM_ID = "a" * 64
TM_ID = "b" * 64
OBSERVER_ID = "c" * 64
SHIM_ID = "d" * 64
INIT_SERVICE_IDS = {
    "kafka-init": "1" * 64,
    "minio-init": "2" * 64,
    "soak-topics-init": "3" * 64,
    "iceberg-init": "4" * 64,
    "serving-init": "5" * 64,
}


def _load(path: Path, module_name: str):
    assert path.exists(), f"missing implementation: {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _runtime():
    return _load(RUNTIME_PATH, "ci_soak_runtime_under_test")


def _shim():
    return _load(SHIM_PATH, "ci_soak_pods_shim_under_test")


def _inspect_payload(
    container_id: str,
    service: str,
    *,
    project: str = PROJECT_NAME,
    restarts: int = 0,
    running: bool = True,
    healthy: bool = True,
) -> dict[str, Any]:
    return {
        "Id": container_id,
        "Name": f"/{project}-{service}-1",
        "RestartCount": restarts,
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": running,
            "Status": "running" if running else "exited",
            "Health": {"Status": "healthy" if healthy else "unhealthy"},
        },
    }


def _completed_inspect_payload(
    container_id: str,
    service: str,
    *,
    project: str = PROJECT_NAME,
    exit_code: int = 0,
    restarts: int = 0,
) -> dict[str, Any]:
    return {
        "Id": container_id,
        "Name": f"/{project}-{service}-1",
        "RestartCount": restarts,
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            }
        },
        "State": {
            "Running": False,
            "Status": "exited",
            "ExitCode": exit_code,
        },
    }


class FakeRunner:
    def __init__(
        self,
        output_dir: Path,
        *,
        fail_steps: set[str] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.fail_steps = fail_steps or set()
        self.calls: list[dict[str, Any]] = []
        self.lookups: list[str] = []

    def which(self, executable: str) -> str | None:
        self.lookups.append(executable)
        return f"C:/fake/{executable}.exe"

    def run(
        self,
        step: str,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ):
        self.calls.append(
            {
                "step": step,
                "argv": tuple(argv),
                "cwd": cwd,
                "env": dict(env or {}),
                "timeout_s": timeout_s,
            }
        )
        runtime = _runtime()
        if step in self.fail_steps:
            return runtime.CommandResult(returncode=1, stdout=f"forced failure: {step}")

        if step == "generate-tls":
            cert_path = Path(argv[argv.index("-out") + 1])
            key_path = Path(argv[argv.index("-keyout") + 1])
            cert_path.write_text("fake cert\n", encoding="utf-8", newline="\n")
            key_path.write_text("fake key\n", encoding="utf-8", newline="\n")
        elif step in {"ps-jm", "ps-jm-final"}:
            return runtime.CommandResult(0, f"{JM_ID}\n")
        elif step in {"ps-tm", "ps-tm-final"}:
            return runtime.CommandResult(0, f"{TM_ID}\n")
        elif step in {"inspect-jm-initial", "inspect-jm-final"}:
            return runtime.CommandResult(
                0,
                json.dumps(_inspect_payload(JM_ID, "flink-jobmanager")),
            )
        elif step in {"inspect-tm-initial", "inspect-tm-final"}:
            return runtime.CommandResult(
                0,
                json.dumps(_inspect_payload(TM_ID, "flink-taskmanager")),
            )
        elif step.startswith("ps-") and step.removeprefix("ps-") in INIT_SERVICE_IDS:
            service = step.removeprefix("ps-")
            return runtime.CommandResult(0, f"{INIT_SERVICE_IDS[service]}\n")
        elif step.startswith("wait-") and step.removeprefix("wait-") in INIT_SERVICE_IDS:
            return runtime.CommandResult(0, "0\n")
        elif step.startswith("inspect-") and step.removeprefix("inspect-") in INIT_SERVICE_IDS:
            service = step.removeprefix("inspect-")
            return runtime.CommandResult(
                0,
                json.dumps(_completed_inspect_payload(INIT_SERVICE_IDS[service], service)),
            )
        elif step == "shim-start":
            return runtime.CommandResult(0, f"{SHIM_ID}\n")
        elif step == "shim-probe":
            return runtime.CommandResult(0, '{"ok":true,"containers":2}\n')
        elif step == "baseline":
            return runtime.CommandResult(0, "result=PASS baseline_all_zero=1\n")
        elif step == "observer-start":
            return runtime.CommandResult(0, f"{OBSERVER_ID}\n")
        elif step == "observer-ready":
            return runtime.CommandResult(0, "observer_start run=test\n")
        elif step == "producer":
            evidence = self.output_dir / "evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / f"{RUN_LABEL}-final.json").write_text(
                json.dumps(
                    {
                        "result": "PASS",
                        "run_label": RUN_LABEL,
                        "attempted": 2000,
                        "delivered": 2000,
                        "failures": 0,
                        "rate_eps": 100.0,
                        "elapsed_s": 20.0,
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )
            return runtime.CommandResult(0, "result=PASS delivered=2000 failures=0\n")
        elif step == "verify":
            evidence = self.output_dir / "evidence"
            (evidence / f"{RUN_LABEL}-soak-verify.json").write_text(
                json.dumps(
                    {
                        "result": "PASS",
                        "run_label": RUN_LABEL,
                        "verify_phase": "soak",
                        "expected": 2000,
                        "rate_contract": "dual_mean_90",
                        "flink": {"job_id": JOB_ID},
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )
            return runtime.CommandResult(0, "result=PASS phase=soak expected=2000\n")

        return runtime.CommandResult(returncode=0, stdout="")


class NoisyDetachedRunner(FakeRunner):
    def run(self, step: str, argv: list[str], **kwargs: Any):
        result = super().run(step, argv, **kwargs)
        runtime = _runtime()
        if step == "shim-start":
            progress = (
                f" Container {PROJECT_NAME}-pods-shim Creating\n"
                f" Container {PROJECT_NAME}-pods-shim Created\n"
            )
            return runtime.CommandResult(0, f"{progress}{SHIM_ID}\n", progress)
        if step == "observer-start":
            progress = (
                f" Container {PROJECT_NAME}-observer Creating\n"
                f" Container {PROJECT_NAME}-observer Created\n"
            )
            return runtime.CommandResult(0, f"{progress}{OBSERVER_ID}\n", progress)
        return result


class RetryProbeRunner(FakeRunner):
    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self.probe_attempts = 0

    def run(self, step: str, argv: list[str], **kwargs: Any):
        result = super().run(step, argv, **kwargs)
        if step != "shim-probe":
            return result
        self.probe_attempts += 1
        runtime = _runtime()
        if self.probe_attempts == 1:
            return runtime.CommandResult(1, "connection refused\n")
        return runtime.CommandResult(0, 'compose notice\n{"ok":true,"containers":2}\n')


class ExistingProjectRunner(FakeRunner):
    def run(self, step: str, argv: list[str], **kwargs: Any):
        result = super().run(step, argv, **kwargs)
        if step == "preflight-volumes":
            runtime = _runtime()
            return runtime.CommandResult(0, "existing-volume-id\n")
        return result


class OneShotFaultRunner(FakeRunner):
    def __init__(self, output_dir: Path, fault: str) -> None:
        super().__init__(output_dir)
        self.fault = fault

    def run(self, step: str, argv: list[str], **kwargs: Any):
        result = super().run(step, argv, **kwargs)
        runtime = _runtime()
        if step == "wait-kafka-init" and self.fault == "exit_code":
            return runtime.CommandResult(0, "1\n")
        if step != "inspect-kafka-init":
            return result

        payload = _completed_inspect_payload(INIT_SERVICE_IDS["kafka-init"], "kafka-init")
        if self.fault == "identity":
            payload["Id"] = "6" * 64
        elif self.fault == "project":
            payload["Config"]["Labels"]["com.docker.compose.project"] = "wrong"
        elif self.fault == "service":
            payload["Config"]["Labels"]["com.docker.compose.service"] = "wrong"
        elif self.fault == "terminal_state":
            payload["State"]["Running"] = True
            payload["State"]["Status"] = "running"
        elif self.fault == "exit_code":
            payload["State"]["ExitCode"] = 1
        return runtime.CommandResult(0, json.dumps(payload))


def _flink_json(path: str) -> dict[str, Any]:
    if path.endswith("/jobs/overview"):
        return {
            "jobs": [
                {
                    "jid": JOB_ID,
                    "state": "RUNNING",
                    "tasks": {"total": 2, "running": 2},
                }
            ]
        }
    if path.endswith(f"/jobs/{JOB_ID}/checkpoints"):
        return {"counts": {"completed": 1, "failed": 0}}
    raise AssertionError(f"unexpected Flink path: {path}")


def _config(runtime, output_dir: Path, *, source_root: Path = FOUNDATION_ROOT):
    return runtime.RuntimeConfig(
        project_root=PROJECT_ROOT,
        source_root=source_root,
        output_dir=output_dir,
        project_name=PROJECT_NAME,
        count=2000,
        rate_eps=100.0,
    )


def test_subprocess_runner_keeps_machine_stdout_separate_from_stderr(
    tmp_path: Path,
) -> None:
    runtime = _runtime()

    result = runtime.SubprocessRunner().run(
        "channel-contract",
        [
            sys.executable,
            "-c",
            "import sys; print('machine'); print('progress', file=sys.stderr)",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout == "machine\n"
    assert result.stderr == "progress\n"


def test_subprocess_runner_preserves_timeout_evidence_on_stderr(
    tmp_path: Path,
) -> None:
    runtime = _runtime()

    result = runtime.SubprocessRunner().run(
        "timeout-step",
        [
            sys.executable,
            "-c",
            (
                "import sys,time;"
                "print('machine', flush=True);"
                "print('progress', file=sys.stderr, flush=True);"
                "time.sleep(30)"
            ),
        ],
        cwd=tmp_path,
        timeout_s=2.0,
    )

    assert result.returncode == 124
    assert result.stdout == "machine\n"
    assert "progress" in result.stderr
    assert "timeout step=timeout-step" in result.stderr


def test_subprocess_runner_preserves_os_error_evidence_on_stderr(
    tmp_path: Path,
) -> None:
    runtime = _runtime()

    result = runtime.SubprocessRunner().run(
        "os-error",
        [str(tmp_path / "missing-runtime-binary")],
        cwd=tmp_path,
    )

    assert result.returncode == 127
    assert result.stdout == ""
    assert "runner_error step=os-error type=" in result.stderr


def test_container_id_parser_accepts_one_full_id_in_r5_compose_transcript() -> None:
    runtime = _runtime()
    transcript = (
        f" Container {PROJECT_NAME}-pods-shim Creating\n"
        f" Container {PROJECT_NAME}-pods-shim Created\n"
        f"{SHIM_ID}\n"
    )

    assert (
        runtime._extract_single_container_id(  # noqa: SLF001 - boundary contract
            transcript,
            reason="shim_container_id_invalid",
        )
        == SHIM_ID
    )


@pytest.mark.parametrize(
    "transcript",
    [
        "Container created without an emitted identity\n",
        f"{SHIM_ID}\n{OBSERVER_ID}\n",
        f"{SHIM_ID[:63]}\n",
        f"docker://{SHIM_ID}\n",
    ],
)
def test_container_id_parser_rejects_zero_or_multiple_ids(transcript: str) -> None:
    runtime = _runtime()

    with pytest.raises(runtime.RuntimeFailure) as caught:
        runtime._extract_single_container_id(  # noqa: SLF001 - boundary contract
            transcript,
            reason="detached_container_id_invalid",
        )

    assert caught.value.reason == "detached_container_id_invalid"


def test_noisy_detached_compose_starts_complete_the_lifecycle(tmp_path: Path) -> None:
    runtime = _runtime()
    output_dir = tmp_path / "out"
    runner = NoisyDetachedRunner(output_dir)

    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is True
    shim_log = (output_dir / "logs" / "shim-start.log").read_text(encoding="utf-8")
    observer_log = (output_dir / "logs" / "observer-start.log").read_text(encoding="utf-8")
    assert SHIM_ID in shim_log
    assert "pods-shim Created" in shim_log
    assert "--- stderr ---" in shim_log
    assert OBSERVER_ID in observer_log
    assert "observer Created" in observer_log
    assert "--- stderr ---" in observer_log


def test_manifest_drift_blocks_all_external_commands(tmp_path: Path) -> None:
    runtime = _runtime()
    source_root = tmp_path / "golden_soak"
    shutil.copytree(FOUNDATION_ROOT, source_root)
    producer = source_root / "pack" / "producer.py"
    producer.write_bytes(producer.read_bytes() + b"\n")

    output_dir = tmp_path / "out"
    runner = FakeRunner(output_dir)
    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir, source_root=source_root),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is False
    assert outcome.reason == "pack_integrity"
    assert runner.lookups == []
    assert runner.calls == []
    terminal = (output_dir / "result-final.txt").read_text(encoding="utf-8")
    assert terminal.startswith("RESULT=FAIL reason=pack_integrity")
    assert "PASS" not in terminal


def test_manifest_rejects_extra_and_traversal_entries(tmp_path: Path) -> None:
    runtime = _runtime()
    source_root = tmp_path / "golden_soak"
    shutil.copytree(FOUNDATION_ROOT, source_root)
    (source_root / "pack" / "extra.py").write_text("pass\n", encoding="utf-8")

    with pytest.raises(runtime.PackIntegrityError):
        runtime.validate_source_pack(source_root)

    (source_root / "pack" / "extra.py").unlink()
    manifest_path = source_root / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["pack/../escape.py"] = {
        "bytes": 0,
        "sha256": "0" * 64,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")

    with pytest.raises(runtime.PackIntegrityError):
        runtime.validate_source_pack(source_root)


def test_ordered_rehearsal_path_is_fail_closed_and_cleans_up(tmp_path: Path) -> None:
    runtime = _runtime()
    output_dir = tmp_path / "out"
    runner = FakeRunner(output_dir)
    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is True
    steps = [call["step"] for call in runner.calls]
    ordered = [
        "generate-tls",
        "preflight-containers",
        "preflight-volumes",
        "preflight-networks",
        "build-flink",
        "build-api",
        "up-core",
        "up-init",
        "wait-kafka-init",
        "wait-minio-init",
        "wait-soak-topics-init",
        "up-data-init",
        "wait-iceberg-init",
        "wait-serving-init",
        "up-app",
        "up-flink-runner",
        "ps-jm",
        "ps-tm",
        "inspect-jm-initial",
        "inspect-tm-initial",
        "shim-start",
        "shim-probe",
        "baseline",
        "observer-start",
        "observer-ready",
        "producer",
        "verify",
        "ps-jm-final",
        "ps-tm-final",
        "inspect-jm-final",
        "inspect-tm-final",
        "collect-ps",
        "collect-logs",
        "observer-remove",
        "shim-remove",
        "compose-down",
    ]
    assert [steps.index(step) for step in ordered] == sorted(steps.index(step) for step in ordered)

    pack_jobs = {"baseline", "observer-start", "producer", "verify"}
    for call in runner.calls:
        if call["step"] in pack_jobs:
            joined = " ".join(call["argv"])
            assert "/golden-pack:ro" in joined
            assert "/evidence" in joined
            assert "--project-name" in joined
            assert PROJECT_NAME in joined

    terminal = (output_dir / "result-final.txt").read_text(encoding="utf-8").strip()
    assert terminal.startswith("RESULT=REHEARSAL_PASS")
    assert "SOAK_PASS" not in terminal
    state = json.loads((output_dir / "runtime-state.json").read_text(encoding="utf-8"))
    assert state["claim_boundary"] == "capacity-independent-compose-rehearsal"
    assert state["container_ids"] == {"jobmanager": JM_ID, "taskmanager": TM_ID}
    assert state["flink"]["job_id"] == JOB_ID


def test_one_shot_waits_bind_stopped_containers_by_exact_identity(tmp_path: Path) -> None:
    runtime = _runtime()
    output_dir = tmp_path / "out"
    runner = FakeRunner(output_dir)

    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is True
    assert not [
        call for call in runner.calls if "compose" in call["argv"] and "wait" in call["argv"]
    ]
    steps = [call["step"] for call in runner.calls]
    for service, container_id in INIT_SERVICE_IDS.items():
        ps_step = f"ps-{service}"
        wait_step = f"wait-{service}"
        inspect_step = f"inspect-{service}"
        assert steps.index(ps_step) < steps.index(wait_step) < steps.index(inspect_step)

        ps_call = next(call for call in runner.calls if call["step"] == ps_step)
        assert ps_call["argv"][-5:] == (
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            service,
        )
        wait_call = next(call for call in runner.calls if call["step"] == wait_step)
        assert wait_call["argv"] == ("C:/fake/docker.exe", "wait", container_id)
        inspect_call = next(call for call in runner.calls if call["step"] == inspect_step)
        assert inspect_call["argv"] == ("C:/fake/docker.exe", "inspect", container_id)


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("identity", "container_inspect_invalid"),
        ("project", "container_project_mismatch"),
        ("service", "container_service_mismatch"),
        ("terminal_state", "one_shot_not_exited"),
        ("exit_code", "one_shot_exit_nonzero"),
    ],
)
def test_one_shot_completion_fails_closed_on_invalid_evidence(
    tmp_path: Path,
    fault: str,
    reason: str,
) -> None:
    runtime = _runtime()
    output_dir = tmp_path / fault
    runner = OneShotFaultRunner(output_dir, fault)

    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is False
    assert outcome.reason == reason
    steps = [call["step"] for call in runner.calls]
    assert "up-data-init" not in steps
    assert "compose-down" in steps


def test_shim_probe_retries_startup_noise_and_compose_runs_are_noninteractive(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    output_dir = tmp_path / "out"
    runner = RetryProbeRunner(output_dir)

    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is True
    assert runner.probe_attempts == 2
    for call in runner.calls:
        argv = call["argv"]
        if "run" in argv and "compose" in argv:
            assert "--no-TTY" in argv


def test_existing_compose_project_resources_block_mutation_and_cleanup(tmp_path: Path) -> None:
    runtime = _runtime()
    output_dir = tmp_path / "out"
    runner = ExistingProjectRunner(output_dir)

    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is False
    assert outcome.reason == "compose_project_not_clean"
    steps = [call["step"] for call in runner.calls]
    assert steps[:3] == ["generate-tls", "preflight-containers", "preflight-volumes"]
    assert "build-flink" not in steps
    assert "compose-down" not in steps


@pytest.mark.parametrize("fail_step", ["baseline", "verify", "compose-down"])
def test_failure_or_cleanup_error_never_publishes_pass(
    tmp_path: Path,
    fail_step: str,
) -> None:
    runtime = _runtime()
    output_dir = tmp_path / fail_step
    runner = FakeRunner(output_dir, fail_steps={fail_step})
    outcome = runtime.RuntimeHarness(
        _config(runtime, output_dir),
        runner=runner,
        http_json=_flink_json,
        sleep=lambda _seconds: None,
    ).execute()

    assert outcome.passed is False
    steps = [call["step"] for call in runner.calls]
    assert "compose-down" in steps
    terminal = (output_dir / "result-final.txt").read_text(encoding="utf-8")
    assert terminal.startswith("RESULT=FAIL")
    assert "PASS" not in terminal


class FakeInspector:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.seen: list[str] = []

    def inspect(self, container_id: str) -> dict[str, Any]:
        self.seen.append(container_id)
        value = self.payloads[container_id]
        if isinstance(value, Exception):
            raise value
        return value


def _shim_config(shim):
    return shim.ShimConfig(
        project_name=PROJECT_NAME,
        jobmanager_id=JM_ID,
        taskmanager_id=TM_ID,
        namespace="agentflow",
        label_selector="app=agentflow-ci-soak-flink",
    )


def test_shim_emits_two_ready_identity_bound_items() -> None:
    shim = _shim()
    inspector = FakeInspector(
        {
            JM_ID: _inspect_payload(JM_ID, "flink-jobmanager"),
            TM_ID: _inspect_payload(TM_ID, "flink-taskmanager"),
        }
    )

    payload = shim.build_pod_list(inspector, _shim_config(shim))

    assert inspector.seen == [JM_ID, TM_ID]
    assert payload["kind"] == "PodList"
    assert len(payload["items"]) == 2
    assert {item["metadata"]["uid"] for item in payload["items"]} == {JM_ID, TM_ID}
    assert all(item["status"]["phase"] == "Running" for item in payload["items"])
    for item in payload["items"]:
        container_status = item["status"]["containerStatuses"][0]
        assert container_status["ready"] is True
        assert container_status["restartCount"] == 0
        assert container_status["containerID"].startswith("docker://")
    encoded = shim.encode_json_response(payload)
    assert len(encoded) <= shim.MAX_RESPONSE_BYTES


@pytest.mark.parametrize(
    ("payloads", "reason"),
    [
        (
            {
                JM_ID: _inspect_payload(JM_ID, "flink-jobmanager", restarts=1),
                TM_ID: _inspect_payload(TM_ID, "flink-taskmanager"),
            },
            "container_restarted",
        ),
        (
            {
                JM_ID: _inspect_payload(JM_ID, "flink-jobmanager", project="wrong"),
                TM_ID: _inspect_payload(TM_ID, "flink-taskmanager"),
            },
            "compose_project_mismatch",
        ),
        (
            {
                JM_ID: {"Id": JM_ID, "State": "malformed"},
                TM_ID: _inspect_payload(TM_ID, "flink-taskmanager"),
            },
            "docker_payload_invalid",
        ),
    ],
)
def test_shim_fails_closed_on_restart_identity_or_malformed_payload(
    payloads: dict[str, Any],
    reason: str,
) -> None:
    shim = _shim()
    with pytest.raises(shim.ShimError, match=reason):
        shim.build_pod_list(FakeInspector(payloads), _shim_config(shim))


def test_shim_auth_and_request_shape_are_strict() -> None:
    shim = _shim()
    expected_bearer = "fixture-value"

    assert shim.is_authorized(f"Bearer {expected_bearer}", expected_bearer) is True
    assert shim.is_authorized("Bearer wrong", expected_bearer) is False
    assert shim.is_authorized("Basic dGVzdA==", expected_bearer) is False

    target = "/api/v1/namespaces/agentflow/pods?labelSelector=app%3Dagentflow-ci-soak-flink"
    assert shim.validate_pod_list_target(
        target,
        namespace="agentflow",
        label_selector="app=agentflow-ci-soak-flink",
    )
    with pytest.raises(shim.ShimError, match="request_target_invalid"):
        shim.validate_pod_list_target(
            target + "&extra=1",
            namespace="agentflow",
            label_selector="app=agentflow-ci-soak-flink",
        )
    with pytest.raises(shim.ShimError, match="request_target_too_large"):
        shim.validate_pod_list_target(
            "/" + ("x" * (shim.MAX_REQUEST_TARGET_BYTES + 1)),
            namespace="agentflow",
            label_selector="app=agentflow-ci-soak-flink",
        )
