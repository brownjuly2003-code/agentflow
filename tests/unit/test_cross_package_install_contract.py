from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = PROJECT_ROOT / "scripts" / "check_cross_package_install.py"


def _load_gate() -> ModuleType:
    assert GATE_PATH.exists(), "the cross-package installability gate is missing"
    spec = importlib.util.spec_from_file_location("check_cross_package_install", GATE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integrations_metadata_requires_the_supported_sdk_major() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "integrations" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert metadata["version"] == "2.0.0"
    assert "agentflow-client>=2,<3" in metadata["dependencies"]


def test_cross_package_gate_installs_both_wheels_together_and_runs_pip_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _load_gate()
    calls: list[list[str]] = []
    monkeypatch.setattr(gate, "_run", lambda command: calls.append(command))
    python = Path("fresh-venv") / "python"
    wheels = (
        Path("wheelhouse") / "agentflow_client-2.0.0-py3-none-any.whl",
        Path("wheelhouse") / "agentflow_integrations-2.0.0-py3-none-any.whl",
    )

    gate._install_and_check(python, wheels)

    assert calls == [
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *(str(wheel) for wheel in wheels),
        ],
        [str(python), "-m", "pip", "check"],
    ]
    assert "--no-deps" not in {argument for command in calls for argument in command}


def test_ci_runs_the_cross_package_installability_gate() -> None:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["test-unit"]["steps"]
    gate_step = next(
        step for step in steps if step.get("name") == "Verify SDK/integrations joint installability"
    )

    assert gate_step["run"].strip() == "python scripts/check_cross_package_install.py"
