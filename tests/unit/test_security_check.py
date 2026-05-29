from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import scripts.security_check as security_check


def test_resolve_requirements_writes_frozen_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        if command[-2:] == ["pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="fastapi==0.115.0\nurllib3==2.2.3\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(security_check.subprocess, "run", fake_run)

    target = tmp_path / "requirements-main.txt"

    count = security_check.resolve_requirements(
        "main",
        ["fastapi>=0.111,<1", "urllib3>=2,<3"],
        target,
        tmp_path,
    )

    assert count == 2
    assert target.read_text(encoding="utf-8").splitlines() == [
        "fastapi==0.115.0",
        "urllib3==2.2.3",
    ]
    assert (tmp_path / "main.in").read_text(encoding="utf-8").splitlines() == [
        "fastapi>=0.111,<1",
        "urllib3>=2,<3",
    ]
    assert calls[0] == [sys.executable, "-m", "venv", str(tmp_path / "safety-main-venv")]


def test_resolve_requirements_rejects_unpinned_freeze_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs):
        if command[-2:] == ["pip", "freeze"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="agentflow @ file:///tmp/agentflow\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(security_check.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="main requirements were not fully resolved"):
        security_check.resolve_requirements(
            "main",
            ["agentflow @ file:///tmp/agentflow"],
            tmp_path / "requirements-main.txt",
            tmp_path,
        )


def test_build_resolved_requirement_files_scans_runtime_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_load_project_dependencies(path: Path) -> list[str]:
        if path.name == "pyproject.toml" and path.parent == security_check.REPO_ROOT:
            return ["fastapi>=0.111,<1"]
        if path.parts[-2:] == ("sdk", "pyproject.toml"):
            return ["httpx>=0.27,<1"]
        if path.parts[-2:] == ("integrations", "pyproject.toml"):
            return [
                "agentflow-client>=1.0",
                "mcp>=1,<2",
                "agentflow-runtime>=1.0",
            ]
        return []

    def fake_load_requirements(path: Path) -> list[str]:
        assert path == security_check.REPO_ROOT / "requirements.txt"
        return ["uvicorn>=0.30,<1"]

    def fake_resolve_requirements(
        name: str, entries: list[str], target: Path, work_dir: Path
    ) -> int:
        assert work_dir == tmp_path
        captured[name] = entries
        target.write_text(f"{name}-package==1.0.0\n", encoding="utf-8")
        return 1

    monkeypatch.setattr(security_check, "load_project_dependencies", fake_load_project_dependencies)
    monkeypatch.setattr(security_check, "load_requirements", fake_load_requirements)
    monkeypatch.setattr(security_check, "resolve_requirements", fake_resolve_requirements)

    main_requirements, sdk_requirements, integrations_requirements = (
        security_check.build_resolved_requirement_files(tmp_path)
    )

    assert captured == {
        "main": ["fastapi>=0.111,<1", "uvicorn>=0.30,<1"],
        "sdk": ["httpx>=0.27,<1"],
        "integrations": ["mcp>=1,<2"],
    }
    assert main_requirements.read_text(encoding="utf-8") == "main-package==1.0.0\n"
    assert sdk_requirements.read_text(encoding="utf-8") == "sdk-package==1.0.0\n"
    assert integrations_requirements.read_text(encoding="utf-8") == "integrations-package==1.0.0\n"
