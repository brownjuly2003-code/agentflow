from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def _write_controller_result(path: Path, line: str) -> None:
    path.write_text(line + "\n", encoding="utf-8", newline="\n")


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
    controller_result_path = tmp_path / "controller-result.txt"
    wrapper_result_path = tmp_path / "wrapper-result.json"
    plan_path = tmp_path / "wrapper-plan.json"
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
    restore_command = [sys.executable, "-c", "raise SystemExit(0)"]
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "controller_command": controller_command,
                "controller_result_path": str(controller_result_path),
                "restore_command": restore_command,
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
    assert payload == {
        "attempt_id": "r-test-supported",
        "controller_invocation": "INVOKED",
        "failure_class": "NONE",
        "first_boundary": "complete",
        "primary_rc": 0,
        "primary_result": CONTROLLER_SUCCESS_LINE,
        "reason": "ok",
        "restore_rc": 0,
        "restore_result": "PASS",
        "result": "PASS",
        "schema_version": 1,
    }
