from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = PROJECT_ROOT / "scripts" / "check_env_matches_lock.py"
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
PINNED_HELM_VERSION = "v3.16.3"


def _load_preflight() -> ModuleType:
    assert PREFLIGHT.is_file(), "environment preflight script is missing"
    spec = importlib.util.spec_from_file_location("check_env_matches_lock", PREFLIGHT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result(
    command: list[str], returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_preflight_reports_synthetic_lock_drift_without_syncing(
    tmp_path: Path, capsys: Any
) -> None:
    module = _load_preflight()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "sync":
            assert kwargs["cwd"] == tmp_path
            assert kwargs["env"]["VIRTUAL_ENV"] == str(Path(sys.prefix).resolve())  # type: ignore[index]
            return _result(
                command,
                1,
                "Would install demo-dependency==2.0.0\nThe environment is outdated\n",
            )
        assert command[1:3] == ["pip", "list"]
        return _result(command, 0, "[]")

    exit_code = module.main(["--project-root", str(tmp_path), "--uv", "uv"], runner=runner)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Would install demo-dependency==2.0.0" in output
    assert "uv sync --active --all-extras --frozen" in output
    assert "--check" in calls[0]
    assert "--offline" in calls[0]
    assert "--inexact" in calls[0]


def test_preflight_reports_stale_workspace_editable(tmp_path: Path, capsys: Any) -> None:
    module = _load_preflight()
    editable = tmp_path / "integrations"
    editable.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-root"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (editable / "pyproject.toml").write_text(
        '[project]\nname = "demo-integrations"\nversion = "2.0.0"\n',
        encoding="utf-8",
    )

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "sync":
            return _result(command, 0, "The environment is synchronized\n")
        installed = [
            {
                "name": "demo-integrations",
                "version": "1.0.0",
                "editable_project_location": str(editable),
            }
        ]
        return _result(command, 0, json.dumps(installed))

    exit_code = module.main(["--project-root", str(tmp_path), "--uv", "uv"], runner=runner)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "demo-integrations" in output
    assert "installed 1.0.0" in output
    assert "workspace metadata declares 2.0.0" in output
    assert "uv pip install --no-deps --editable" in output


def test_preflight_accepts_synchronized_environment_control(tmp_path: Path, capsys: Any) -> None:
    module = _load_preflight()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8"
    )

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "sync":
            return _result(command, 0, "The environment is synchronized\n")
        installed = [
            {
                "name": "demo",
                "version": "1.2.3",
                "editable_project_location": str(tmp_path),
            }
        ]
        return _result(command, 0, json.dumps(installed))

    exit_code = module.main(["--project-root", str(tmp_path), "--uv", "uv"], runner=runner)

    assert exit_code == 0
    assert "matches uv.lock and editable workspace metadata" in capsys.readouterr().out


def test_every_setup_helm_usage_pins_an_exact_version() -> None:
    setup_steps: list[tuple[Path, dict[str, object]]] = []
    for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("azure/setup-helm@"):
                    setup_steps.append((workflow_path, step))

    assert setup_steps
    for workflow_path, step in setup_steps:
        version = str(step.get("with", {}).get("version", ""))  # type: ignore[union-attr]
        assert re.fullmatch(r"v\d+\.\d+\.\d+", version), workflow_path
        assert version == PINNED_HELM_VERSION, workflow_path


def test_ci_logs_the_pinned_helm_version() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["helm-schema-live"]["steps"]
    setup_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("azure/setup-helm@")
    )

    assert steps[setup_index]["with"]["version"] == PINNED_HELM_VERSION
    assert any("helm version --short" in str(step.get("run", "")) for step in steps)


def test_testing_docs_make_the_environment_preflight_a_release_gate() -> None:
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            PROJECT_ROOT / "docs" / "operations" / "testing-control-plane.md",
            PROJECT_ROOT / "docs" / "contributing.md",
        )
    ).lower()

    assert "scripts/check_env_matches_lock.py" in docs
    assert "pre-release" in docs
    assert "pre-audit" in docs
    assert "pip check" in docs
    assert "release evidence" in docs
