from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = PROJECT_ROOT / "scripts" / "golden_soak" / "architecture_gate.py"
EXACT_HEAD = "a" * 40


def _load_gate():
    assert GATE_PATH.exists(), f"missing implementation: {GATE_PATH}"
    spec = importlib.util.spec_from_file_location("ci_soak_architecture_gate_under_test", GATE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeCommandResult:
    returncode: int
    stdout: str = ""


class FakeRunner:
    def __init__(self, outcomes: dict[str, FakeCommandResult]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def run(self, check, *, cwd: Path):
        assert cwd == PROJECT_ROOT
        self.calls.append(check.name)
        return self.outcomes[check.name]


def _passing_runner(module, config, **overrides: FakeCommandResult) -> FakeRunner:
    outcomes = {check.name: FakeCommandResult(returncode=0) for check in config.command_checks}
    outcomes[config.head_check.name] = FakeCommandResult(returncode=0, stdout=EXACT_HEAD + "\n")
    outcomes.update(overrides)
    return FakeRunner(outcomes)


def test_gate_pass_prints_exactly_one_terminal_line(capsys) -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    runner = _passing_runner(module, config)

    returncode = module.main([], config=config, runner=runner)

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [f"ARCHITECTURE_READY=PASS blockers=0 head={EXACT_HEAD}"]
    assert captured.err == ""
    assert returncode == 0
    assert runner.calls == [
        *(check.name for check in config.command_checks),
        config.head_check.name,
    ]


def test_gate_batches_failures_without_retry_and_keeps_one_line(capsys) -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    runner = _passing_runner(
        module,
        config,
        focused_tests=FakeCommandResult(returncode=1),
        compose_config=FakeCommandResult(returncode=17),
        clean_tree=FakeCommandResult(returncode=1),
    )

    returncode = module.main([], config=config, runner=runner)

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"ARCHITECTURE_READY=BLOCKED blockers=G-TESTS,G-COMPOSE,G-CLEAN head={EXACT_HEAD}"
    ]
    assert captured.err == ""
    assert returncode == 1
    for check in (*config.command_checks, config.head_check):
        assert runner.calls.count(check.name) == 1


def test_gate_reports_the_specific_unclosed_audit_finding(tmp_path: Path) -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    audit_lines = config.audit_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(audit_lines):
        if line.startswith("| `A-05` |"):
            audit_lines[index] = line.replace("; `CLOSED-LOCAL` 2026-08-20", "")
            break
    else:
        raise AssertionError("A-05 register row missing from audit fixture")
    audit_path = tmp_path / "audit.md"
    audit_path.write_text("\n".join(audit_lines) + "\n", encoding="utf-8", newline="\n")
    config = replace(config, audit_path=audit_path)

    result = module.evaluate_gate(config, _passing_runner(module, config))

    assert result.status == "BLOCKED"
    assert result.blockers == ("A-05",)
    assert result.head == EXACT_HEAD


def test_gate_fails_closed_on_pack_manifest_or_encoding_drift(tmp_path: Path) -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    bad_text = tmp_path / "bad.txt"
    bad_text.write_bytes(b"crlf\r\n")
    config = replace(
        config,
        pack_root=tmp_path / "missing-pack-root",
        text_paths=(bad_text,),
    )

    result = module.evaluate_gate(config, _passing_runner(module, config))

    assert result.status == "BLOCKED"
    assert result.blockers == ("G-PACK", "G-ENCODING")


def test_gate_rejects_non_exact_head_evidence() -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    runner = _passing_runner(
        module,
        config,
        head=FakeCommandResult(returncode=0, stdout="main\nextra\n"),
    )

    result = module.evaluate_gate(config, runner)

    assert result.status == "BLOCKED"
    assert result.blockers == ("G-HEAD",)
    assert result.head == "UNKNOWN"


def test_gate_command_contract_matches_the_documented_local_checks() -> None:
    module = _load_gate()
    config = module.build_config(PROJECT_ROOT)
    commands = {check.name: check.argv for check in config.command_checks}

    assert commands["focused_tests"] == (
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/test_ci_soak_runtime.py",
        "tests/unit/test_ci_soak_foundation.py",
        "tests/unit/test_ci_soak_wrapper.py",
        "-q",
    )
    assert commands["ruff_check"][:4] == (sys.executable, "-m", "ruff", "check")
    assert commands["ruff_format"][:5] == (
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--check",
    )
    assert commands["compose_config"] == (
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.flink.yml",
        "-f",
        "docker-compose.soak.yml",
        "config",
        "--quiet",
    )
    assert commands["diff_check"] == ("git", "diff", "--check", "HEAD", "--")
    assert commands["clean_tree"] == ("git", "diff", "--quiet", "HEAD", "--")
    assert config.head_check.argv == ("git", "rev-parse", "HEAD")


def test_subprocess_runner_suppresses_nonterminal_child_output(capsys) -> None:
    module = _load_gate()
    check = module.CommandCheck(
        name="noisy",
        blocker="G-NOISY",
        argv=(sys.executable, "-c", "print('must-not-leak')"),
        timeout_seconds=10,
    )

    result = module.SubprocessRunner().run(check, cwd=PROJECT_ROOT)

    captured = capsys.readouterr()
    assert result.returncode == 0
    assert result.stdout == ""
    assert captured.out == ""
    assert captured.err == ""
