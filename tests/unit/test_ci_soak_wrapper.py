from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SOAK_ROOT = PROJECT_ROOT / "scripts" / "golden_soak"
BOOTSTRAP_PATH = GOLDEN_SOAK_ROOT / "bootstrap.sh"
WRAPPER_PATH = GOLDEN_SOAK_ROOT / "wrapper.py"

CONTROLLER_SUCCESS_LINE = (
    "RESULT=REHEARSAL_PASS run=golden-4h-soak-test count=2000 "
    "gate=capacity-independent-rehearsal-only"
)


def _load_wrapper():
    assert WRAPPER_PATH.exists(), f"missing implementation: {WRAPPER_PATH}"
    spec = importlib.util.spec_from_file_location("ci_soak_wrapper_under_test", WRAPPER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    def __init__(self, outcomes: dict[tuple[str, ...], int | OSError]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> int:
        self.calls.append(argv)
        outcome = self.outcomes[argv]
        if isinstance(outcome, OSError):
            raise outcome
        return outcome


@dataclass(frozen=True)
class FakeCommandResult:
    returncode: int
    stdout: str


class TransitionRunner:
    def __init__(
        self,
        *,
        run_outcomes: dict[tuple[str, ...], int | OSError],
        probe_outcomes: dict[
            tuple[str, ...],
            tuple[int, str] | OSError | list[tuple[int, str] | OSError],
        ],
        hooks: dict[tuple[str, ...], object] | None = None,
    ) -> None:
        self.run_outcomes = run_outcomes
        self.probe_outcomes = probe_outcomes
        self.hooks = hooks or {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def _hook(self, argv: tuple[str, ...]) -> None:
        hook = self.hooks.get(argv)
        if hook is not None:
            hook()

    def run(self, argv: tuple[str, ...]) -> int:
        self.calls.append(("run", argv))
        self._hook(argv)
        outcome = self.run_outcomes[argv]
        if isinstance(outcome, OSError):
            raise outcome
        return outcome

    def probe(self, argv: tuple[str, ...]) -> FakeCommandResult:
        self.calls.append(("probe", argv))
        self._hook(argv)
        configured = self.probe_outcomes[argv]
        if isinstance(configured, list):
            assert configured, f"exhausted probe transitions for {argv!r}"
            outcome = configured.pop(0)
        else:
            outcome = configured
        if isinstance(outcome, OSError):
            raise outcome
        return FakeCommandResult(returncode=outcome[0], stdout=outcome[1])


def _write_controller_result(path: Path, line: str) -> None:
    path.write_text(line + "\n", encoding="utf-8", newline="\n")


def _guarded_fixture(
    module,
    tmp_path: Path,
    *,
    livez_transitions: list[tuple[int, str]] | None = None,
    livez_max_attempts: int = 3,
):
    shared_root = tmp_path / "shared"
    snapshot_path = shared_root / "snapshot"
    output_parent_path = shared_root / "outputs"
    snapshot_path.mkdir(parents=True)
    output_parent_path.mkdir()
    controller_result_path = output_parent_path / "controller-result.txt"
    _write_controller_result(controller_result_path, CONTROLLER_SUCCESS_LINE)

    commands = {
        "source": ("probe", "source"),
        "source_cleanup": ("probe-cleanup", "source"),
        "output": ("probe", "output"),
        "output_cleanup": ("probe-cleanup", "output"),
        "clickhouse_container": ("probe", "clickhouse-container-health"),
        "clickhouse_host": ("probe", "clickhouse-host-route"),
        "clickhouse_workload": ("probe", "clickhouse-workload-route"),
        "stop": ("stop",),
        "controller": ("controller",),
        "restore": ("restore",),
        "kind_identity": ("probe", "kind-identity"),
        "kind_running": ("probe", "kind-running"),
        "kind_restart": ("probe", "kind-restart-count"),
        "kind_apiserver": ("probe", "kind-apiserver-count"),
        "kind_livez": ("probe", "kind-livez"),
    }
    source_sha256 = "1" * 64
    output_sha256 = "2" * 64
    kind_container_id = "a" * 64
    plan = module.GuardedPlan(
        shared_root=shared_root,
        snapshot_path=snapshot_path,
        output_parent_path=output_parent_path,
        owner_lock_path=shared_root / ".ci-soak-owner.lock",
        source_probe=module.VisibilityProbe(
            command=commands["source"],
            expected_sha256=source_sha256,
            cleanup_command=commands["source_cleanup"],
        ),
        output_probe=module.VisibilityProbe(
            command=commands["output"],
            expected_sha256=output_sha256,
            cleanup_command=commands["output_cleanup"],
        ),
        clickhouse=module.ClickHouseProbes(
            container_health=module.ExactProbe(
                command=commands["clickhouse_container"], expected_output="healthy"
            ),
            host_route=module.ExactProbe(command=commands["clickhouse_host"], expected_output="1"),
            workload_route=module.ExactProbe(
                command=commands["clickhouse_workload"], expected_output="1"
            ),
        ),
        stop_command=commands["stop"],
        controller_command=commands["controller"],
        controller_result_path=controller_result_path,
        restore_command=commands["restore"],
        kind_restore=module.KindRestoreContract(
            container_id=kind_container_id,
            identity_command=commands["kind_identity"],
            running_command=commands["kind_running"],
            restart_count_command=commands["kind_restart"],
            apiserver_count_command=commands["kind_apiserver"],
            livez_command=commands["kind_livez"],
            livez_max_attempts=livez_max_attempts,
            livez_consecutive_successes=2,
        ),
    )
    runner = TransitionRunner(
        run_outcomes={
            commands["stop"]: 0,
            commands["controller"]: 0,
            commands["restore"]: 0,
        },
        probe_outcomes={
            commands["source"]: (0, source_sha256),
            commands["source_cleanup"]: (0, "absent"),
            commands["output"]: (0, output_sha256),
            commands["output_cleanup"]: (0, "absent"),
            commands["clickhouse_container"]: (0, "healthy"),
            commands["clickhouse_host"]: (0, "1"),
            commands["clickhouse_workload"]: (0, "1"),
            commands["kind_identity"]: (0, kind_container_id),
            commands["kind_running"]: (0, "running"),
            commands["kind_restart"]: (0, "0"),
            commands["kind_apiserver"]: (0, "1"),
            commands["kind_livez"]: list(livez_transitions or [(0, "ok"), (0, "ok")]),
        },
    )
    return plan, runner, commands


def _bash_executable() -> str:
    if os.name == "nt":
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        if git_bash.is_file():
            return str(git_bash)
    executable = shutil.which("bash")
    assert executable is not None, "bash is required for CI-soak bootstrap fixtures"
    return executable


def _run_bootstrap(
    *,
    attempt_id: str,
    result_path: Path,
    candidates: tuple[str, ...],
    wrapper_args: tuple[str, ...] = (),
    wrapper_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    assert BOOTSTRAP_PATH.exists(), f"missing implementation: {BOOTSTRAP_PATH}"
    env = os.environ.copy()
    env["CI_SOAK_PYTHON_CANDIDATES"] = "\n".join(candidates)
    env.pop("CI_SOAK_WRAPPER_PATH", None)
    if wrapper_path is not None:
        env["CI_SOAK_WRAPPER_PATH"] = wrapper_path.as_posix()
    return subprocess.run(  # noqa: S603
        [
            _bash_executable(),
            BOOTSTRAP_PATH.as_posix(),
            attempt_id,
            result_path.as_posix(),
            *wrapper_args,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _terminal_payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    prefix = "WRAPPER_RESULT="
    assert lines[0].startswith(prefix)
    return json.loads(lines[0][len(prefix) :])


def test_controller_launch_error_is_explicitly_not_invoked_and_still_restores(
    tmp_path: Path,
) -> None:
    module = _load_wrapper()
    controller = ("controller",)
    restore = ("restore",)
    runner = FakeRunner({controller: OSError("not executable"), restore: 0})

    record = module.execute_attempt(
        attempt_id="r-test-launch",
        controller_command=controller,
        controller_result_path=tmp_path / "controller-result.txt",
        restore_command=restore,
        runner=runner,
    ).as_dict()

    assert runner.calls == [controller, restore]
    assert record["result"] == "FAIL"
    assert record["failure_class"] == "WRAPPER_FAILURE"
    assert record["first_boundary"] == "controller_launch"
    assert record["reason"] == "controller_not_invoked"
    assert record["controller_invocation"] == "NOT_INVOKED"
    assert record["primary_rc"] is None
    assert record["primary_result"] == "NOT_INVOKED"
    assert record["restore_rc"] == 0
    assert record["restore_result"] == "PASS"


def test_controller_failure_is_distinct_from_not_invoked_and_preserves_result(
    tmp_path: Path,
) -> None:
    module = _load_wrapper()
    controller = ("controller",)
    restore = ("restore",)
    controller_result_path = tmp_path / "controller-result.txt"
    primary_result = "RESULT=FAIL reason=up_app_failed"
    _write_controller_result(controller_result_path, primary_result)
    runner = FakeRunner({controller: 23, restore: 0})

    record = module.execute_attempt(
        attempt_id="r-test-controller",
        controller_command=controller,
        controller_result_path=controller_result_path,
        restore_command=restore,
        runner=runner,
    ).as_dict()

    assert record["result"] == "FAIL"
    assert record["failure_class"] == "CONTROLLER_FAILURE"
    assert record["first_boundary"] == "controller"
    assert record["reason"] == "controller_failed"
    assert record["controller_invocation"] == "INVOKED"
    assert record["primary_rc"] == 23
    assert record["primary_result"] == primary_result
    assert record["restore_rc"] == 0


def test_zero_controller_rc_without_terminal_result_cannot_publish_pass(tmp_path: Path) -> None:
    module = _load_wrapper()
    controller = ("controller",)
    restore = ("restore",)
    runner = FakeRunner({controller: 0, restore: 0})

    record = module.execute_attempt(
        attempt_id="r-test-result-missing",
        controller_command=controller,
        controller_result_path=tmp_path / "missing-controller-result.txt",
        restore_command=restore,
        runner=runner,
    ).as_dict()

    assert record["result"] == "FAIL"
    assert record["failure_class"] == "CONTROLLER_FAILURE"
    assert record["first_boundary"] == "controller"
    assert record["reason"] == "controller_result_missing"
    assert record["controller_invocation"] == "INVOKED"
    assert record["primary_rc"] == 0
    assert record["primary_result"] == "MISSING"
    assert record["restore_rc"] == 0


def test_restore_failure_overrides_candidate_pass_without_erasing_primary_result(
    tmp_path: Path,
) -> None:
    module = _load_wrapper()
    controller = ("controller",)
    restore = ("restore",)
    controller_result_path = tmp_path / "controller-result.txt"
    _write_controller_result(controller_result_path, CONTROLLER_SUCCESS_LINE)
    runner = FakeRunner({controller: 0, restore: 17})

    record = module.execute_attempt(
        attempt_id="r-test-restore",
        controller_command=controller,
        controller_result_path=controller_result_path,
        restore_command=restore,
        runner=runner,
    ).as_dict()

    assert record["result"] == "FAIL"
    assert record["failure_class"] == "WRAPPER_FAILURE"
    assert record["first_boundary"] == "restore"
    assert record["reason"] == "restore_failed"
    assert record["primary_rc"] == 0
    assert record["primary_result"] == CONTROLLER_SUCCESS_LINE
    assert record["restore_rc"] == 17
    assert record["restore_result"] == "FAIL"


def test_primary_failure_keeps_precedence_when_restore_also_fails(tmp_path: Path) -> None:
    module = _load_wrapper()
    controller = ("controller",)
    restore = ("restore",)
    controller_result_path = tmp_path / "controller-result.txt"
    primary_result = "RESULT=FAIL reason=verify_failed"
    _write_controller_result(controller_result_path, primary_result)
    runner = FakeRunner({controller: 7, restore: 17})

    record = module.execute_attempt(
        attempt_id="r-test-both-fail",
        controller_command=controller,
        controller_result_path=controller_result_path,
        restore_command=restore,
        runner=runner,
    ).as_dict()

    assert record["failure_class"] == "CONTROLLER_FAILURE"
    assert record["first_boundary"] == "controller"
    assert record["reason"] == "controller_failed"
    assert record["primary_rc"] == 7
    assert record["primary_result"] == primary_result
    assert record["restore_rc"] == 17
    assert record["restore_result"] == "FAIL"


@pytest.mark.parametrize(
    ("path_field", "reason"),
    [
        ("snapshot_path", "snapshot_outside_shared_root"),
        ("output_parent_path", "output_parent_outside_shared_root"),
    ],
)
def test_guarded_path_policy_rejects_paths_outside_shared_root_before_commands(
    tmp_path: Path,
    path_field: str,
    reason: str,
) -> None:
    module = _load_wrapper()
    plan, runner, _commands = _guarded_fixture(module, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    plan = replace(plan, **{path_field: outside})

    record = module.execute_guarded_attempt(
        attempt_id=f"r-test-{path_field}", plan=plan, runner=runner
    ).as_dict()

    assert runner.calls == []
    assert record["result"] == "FAIL"
    assert record["failure_class"] == "INFRASTRUCTURE_CONTRACT_FAILURE"
    assert record["first_boundary"] == "path_policy"
    assert record["reason"] == reason
    assert record["controller_invocation"] == "NOT_INVOKED"
    assert record["restore_result"] == "NOT_INVOKED"
    assert record["lock_result"] == "RELEASED"
    assert not plan.owner_lock_path.exists()


def test_guarded_preflight_names_both_visibility_probes_and_cleans_before_stop(
    tmp_path: Path,
) -> None:
    module = _load_wrapper()
    plan, runner, commands = _guarded_fixture(module, tmp_path)
    lock_observations: list[bool] = []
    runner.hooks[commands["stop"]] = lambda: lock_observations.append(plan.owner_lock_path.is_dir())
    runner.hooks[commands["kind_livez"]] = lambda: lock_observations.append(
        plan.owner_lock_path.is_dir()
    )

    record = module.execute_guarded_attempt(
        attempt_id="r-test-guarded-pass", plan=plan, runner=runner
    ).as_dict()

    assert record["result"] == "PASS"
    assert record["lock_result"] == "RELEASED"
    assert record["stop_rc"] == 0
    assert lock_observations == [True, True, True]
    assert not plan.owner_lock_path.exists()
    assert runner.calls[:7] == [
        ("probe", commands["source"]),
        ("probe", commands["source_cleanup"]),
        ("probe", commands["output"]),
        ("probe", commands["output_cleanup"]),
        ("probe", commands["clickhouse_container"]),
        ("probe", commands["clickhouse_host"]),
        ("probe", commands["clickhouse_workload"]),
    ]
    assert runner.calls[7] == ("run", commands["stop"])
    check_names = [check["name"] for check in record["checks"]]
    assert check_names[:9] == [
        "snapshot_containment",
        "output_parent_containment",
        "source_visibility",
        "source_probe_cleanup",
        "output_visibility",
        "output_probe_cleanup",
        "clickhouse_container_health",
        "clickhouse_host_route",
        "clickhouse_workload_route",
    ]


@pytest.mark.parametrize(
    ("command_name", "classification", "reason"),
    [
        (
            "clickhouse_container",
            "SERVICE_HEALTH_FAILURE",
            "clickhouse_container_health_failed",
        ),
        ("clickhouse_host", "HOST_ROUTE_FAILURE", "clickhouse_host_route_failed"),
        (
            "clickhouse_workload",
            "WORKLOAD_ROUTE_FAILURE",
            "clickhouse_workload_route_failed",
        ),
    ],
)
def test_clickhouse_viewpoints_are_classified_once_without_raw_retry(
    tmp_path: Path,
    command_name: str,
    classification: str,
    reason: str,
) -> None:
    module = _load_wrapper()
    plan, runner, commands = _guarded_fixture(module, tmp_path)
    runner.probe_outcomes[commands[command_name]] = (28, "unreachable")

    record = module.execute_guarded_attempt(
        attempt_id=f"r-test-{command_name}", plan=plan, runner=runner
    ).as_dict()

    assert record["result"] == "FAIL"
    assert record["failure_class"] == "INFRASTRUCTURE_CONTRACT_FAILURE"
    assert record["first_boundary"] == "clickhouse_preflight"
    assert record["reason"] == reason
    assert record["stop_rc"] is None
    assert record["restore_result"] == "NOT_INVOKED"
    viewpoint_checks = [
        check for check in record["checks"] if check["name"].startswith("clickhouse_")
    ]
    assert [check["name"] for check in viewpoint_checks] == [
        "clickhouse_container_health",
        "clickhouse_host_route",
        "clickhouse_workload_route",
    ]
    failed = [check for check in viewpoint_checks if check["result"] == "FAIL"]
    assert len(failed) == 1
    assert failed[0]["classification"] == classification
    for command_key in (
        "clickhouse_container",
        "clickhouse_host",
        "clickhouse_workload",
    ):
        assert runner.calls.count(("probe", commands[command_key])) == 1
    assert ("run", commands["stop"]) not in runner.calls


def test_kind_restore_waits_for_two_consecutive_livez_successes(tmp_path: Path) -> None:
    module = _load_wrapper()
    plan, runner, commands = _guarded_fixture(
        module,
        tmp_path,
        livez_transitions=[(22, "http_500"), (0, "ok"), (0, "ok")],
    )

    record = module.execute_guarded_attempt(
        attempt_id="r-test-kind-delayed", plan=plan, runner=runner
    ).as_dict()

    assert record["result"] == "PASS"
    assert record["restore_result"] == "PASS"
    assert runner.calls.count(("probe", commands["kind_livez"])) == 3
    livez_checks = [check for check in record["checks"] if check["name"].startswith("kind_livez_")]
    assert [check["result"] for check in livez_checks] == ["FAIL", "PASS", "PASS"]


def test_kind_restore_cannot_pass_after_only_one_livez_success(tmp_path: Path) -> None:
    module = _load_wrapper()
    plan, runner, commands = _guarded_fixture(
        module,
        tmp_path,
        livez_transitions=[(22, "http_500"), (0, "ok")],
        livez_max_attempts=2,
    )

    record = module.execute_guarded_attempt(
        attempt_id="r-test-kind-not-ready", plan=plan, runner=runner
    ).as_dict()

    assert record["result"] == "FAIL"
    assert record["failure_class"] == "INFRASTRUCTURE_CONTRACT_FAILURE"
    assert record["first_boundary"] == "restore_kind_livez"
    assert record["reason"] == "kind_livez_not_ready"
    assert record["primary_result"] == CONTROLLER_SUCCESS_LINE
    assert record["restore_rc"] == 0
    assert record["restore_result"] == "FAIL"
    assert runner.calls.count(("probe", commands["kind_livez"])) == 2


def test_owner_lock_fails_closed_for_invalid_stale_state(tmp_path: Path) -> None:
    module = _load_wrapper()
    lock_path = tmp_path / "owner.lock"
    lock_path.mkdir()

    lock = module.ExclusiveOwnerLock(lock_path, "r-test-stale-lock")
    with pytest.raises(module.OwnerLockError, match="owner_lock_state_invalid"):
        lock.acquire()

    assert lock_path.is_dir()


def test_owner_lock_allows_only_one_process_to_enter_stop_boundary(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "owner.lock"
    boundary_path = tmp_path / "stop-boundary.txt"
    release_path = tmp_path / "release-first"
    worker = """
import importlib.util
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("ci_soak_wrapper_worker", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
lock = module.ExclusiveOwnerLock(Path(sys.argv[2]), sys.argv[5])
try:
    lock.acquire()
except module.OwnerLockError as exc:
    print(exc.reason, flush=True)
    raise SystemExit(75)
with Path(sys.argv[3]).open("a", encoding="utf-8", newline="\\n") as stream:
    stream.write(sys.argv[5] + "\\n")
if sys.argv[6] == "hold":
    deadline = time.monotonic() + 5
    while not Path(sys.argv[4]).exists() and time.monotonic() < deadline:
        time.sleep(0.02)
lock.release()
"""
    first = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            worker,
            str(WRAPPER_PATH),
            str(lock_path),
            str(boundary_path),
            str(release_path),
            "owner-a",
            "hold",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    deadline = time.monotonic() + 5
    while not boundary_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert boundary_path.exists(), first.communicate(timeout=1)
    owner = json.loads((lock_path / "owner.json").read_text(encoding="utf-8"))
    assert owner["attempt_id"] == "owner-a"
    assert owner["pid"] == first.pid
    assert owner["token"]

    second = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            worker,
            str(WRAPPER_PATH),
            str(lock_path),
            str(boundary_path),
            str(release_path),
            "owner-b",
            "try",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    release_path.write_text("release\n", encoding="utf-8", newline="\n")
    first_stdout, first_stderr = first.communicate(timeout=10)

    assert first.returncode == 0, (first_stdout, first_stderr)
    assert second.returncode == 75
    assert second.stdout.strip() == "owner_lock_busy"
    assert boundary_path.read_text(encoding="utf-8").splitlines() == ["owner-a"]
    assert not lock_path.exists()


def test_bootstrap_records_absent_interpreter_as_not_invoked(tmp_path: Path) -> None:
    result_path = tmp_path / "absent-interpreter.json"

    completed = _run_bootstrap(
        attempt_id="r-test-absent",
        result_path=result_path,
        candidates=("ci-soak-python-definitely-absent",),
    )

    assert completed.returncode != 0
    payload = _terminal_payload(completed)
    assert json.loads(result_path.read_text(encoding="utf-8")) == payload
    assert payload["attempt_id"] == "r-test-absent"
    assert payload["failure_class"] == "WRAPPER_FAILURE"
    assert payload["first_boundary"] == "bootstrap"
    assert payload["reason"] == "supported_python_not_found"
    assert payload["controller_invocation"] == "NOT_INVOKED"
    assert payload["primary_rc"] is None
    assert payload["restore_rc"] is None


def test_bootstrap_rejects_present_but_unsupported_interpreter(tmp_path: Path) -> None:
    result_path = tmp_path / "unsupported-interpreter.json"

    completed = _run_bootstrap(
        attempt_id="r-test-unsupported",
        result_path=result_path,
        candidates=("false",),
    )

    assert completed.returncode != 0
    payload = _terminal_payload(completed)
    assert json.loads(result_path.read_text(encoding="utf-8")) == payload
    assert payload["reason"] == "supported_python_not_found"
    assert payload["controller_invocation"] == "NOT_INVOKED"


def test_bootstrap_persists_orchestration_stop_when_wrapper_emits_no_terminal(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "orchestration-stop.json"

    completed = _run_bootstrap(
        attempt_id="r-test-orchestration",
        result_path=result_path,
        candidates=(Path(sys.executable).as_posix(),),
        wrapper_path=tmp_path / "missing-wrapper.py",
    )

    assert completed.returncode != 0
    payload = _terminal_payload(completed)
    assert json.loads(result_path.read_text(encoding="utf-8")) == payload
    assert payload["failure_class"] == "ORCHESTRATION_STOP"
    assert payload["first_boundary"] == "wrapper_launch"
    assert payload["reason"] == "wrapper_terminal_missing"
    assert payload["controller_invocation"] == "NOT_INVOKED"
    assert payload["primary_rc"] is None
    assert payload["restore_rc"] is None


def test_bootstrap_uses_supported_fallback_and_emits_exactly_one_terminal_record(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared"
    snapshot_path = shared_root / "snapshot"
    output_parent_path = shared_root / "outputs"
    snapshot_path.mkdir(parents=True)
    output_parent_path.mkdir()
    controller_result_path = output_parent_path / "controller-result.txt"
    wrapper_result_path = output_parent_path / "wrapper-result.json"
    plan_path = tmp_path / "wrapper-plan.json"
    source_sha256 = "1" * 64
    output_sha256 = "2" * 64
    kind_container_id = "a" * 64
    controller_command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import sys; "
            "Path(sys.argv[1]).write_text(sys.argv[2] + '\\n', "
            "encoding='utf-8', newline='\\n')"
        ),
        str(controller_result_path),
        CONTROLLER_SUCCESS_LINE,
    ]
    success_command = [sys.executable, "-c", "raise SystemExit(0)"]

    def probe_command(output: str) -> list[str]:
        return [sys.executable, "-c", "import sys; print(sys.argv[1])", output]

    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "shared_root": str(shared_root),
                "snapshot_path": str(snapshot_path),
                "output_parent_path": str(output_parent_path),
                "owner_lock_path": str(shared_root / ".ci-soak-owner.lock"),
                "source_probe": {
                    "command": probe_command(source_sha256),
                    "expected_sha256": source_sha256,
                    "cleanup_command": probe_command("absent"),
                },
                "output_probe": {
                    "command": probe_command(output_sha256),
                    "expected_sha256": output_sha256,
                    "cleanup_command": probe_command("absent"),
                },
                "clickhouse_probes": {
                    "container_health": {
                        "command": probe_command("healthy"),
                        "expected_output": "healthy",
                    },
                    "host_route": {
                        "command": probe_command("1"),
                        "expected_output": "1",
                    },
                    "workload_route": {
                        "command": probe_command("1"),
                        "expected_output": "1",
                    },
                },
                "stop_command": success_command,
                "controller_command": controller_command,
                "controller_result_path": str(controller_result_path),
                "restore_command": success_command,
                "kind_restore": {
                    "container_id": kind_container_id,
                    "identity_command": probe_command(kind_container_id),
                    "running_command": probe_command("running"),
                    "restart_count_command": probe_command("0"),
                    "apiserver_count_command": probe_command("1"),
                    "livez_command": probe_command("ok"),
                    "livez_max_attempts": 3,
                    "livez_consecutive_successes": 2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    completed = _run_bootstrap(
        attempt_id="r-test-supported",
        result_path=wrapper_result_path,
        candidates=("false", Path(sys.executable).as_posix()),
        wrapper_args=(
            "--plan-path",
            plan_path.as_posix(),
        ),
    )

    assert completed.returncode == 0, completed.stderr
    payload = _terminal_payload(completed)
    assert wrapper_result_path.read_text(encoding="utf-8").splitlines() == [
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    ]
    assert payload["attempt_id"] == "r-test-supported"
    assert payload["controller_invocation"] == "INVOKED"
    assert payload["failure_class"] == "NONE"
    assert payload["first_boundary"] == "complete"
    assert payload["primary_rc"] == 0
    assert payload["primary_result"] == CONTROLLER_SUCCESS_LINE
    assert payload["restore_rc"] == 0
    assert payload["restore_result"] == "PASS"
    assert payload["lock_result"] == "RELEASED"
    assert payload["result"] == "PASS"
    assert payload["schema_version"] == 1
    assert [check["name"] for check in payload["checks"]][-2:] == [
        "kind_livez_1",
        "kind_livez_2",
    ]
