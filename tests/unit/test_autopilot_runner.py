from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_autopilot_accepts_clean_worktree_with_no_initial_changes(tmp_path):
    powershell = shutil.which("powershell")
    assert powershell is not None

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / ".gitignore").write_text(".autopilot/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Autopilot Test",
            "-c",
            "user.email=autopilot@example.invalid",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "pi.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                "if not exist .autopilot mkdir .autopilot",
                "echo task title> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo docs/operations/> .autopilot\\allowed-paths.txt",
                "echo test commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )
    (shim_dir / "codex.cmd").write_text(
        "@echo off\n"
        ":check_args\n"
        'if "%~1"=="" goto done\n'
        'if "%~1"=="--ask-for-approval" exit /b 2\n'
        "shift\n"
        "goto check_args\n"
        ":done\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "autopilot.ps1"),
            "-RepoRoot",
            str(repo),
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Autopilot run finished." in result.stdout


def test_autopilot_falls_back_to_codex_planner_when_pi_fails(tmp_path):
    powershell = shutil.which("powershell")
    assert powershell is not None

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / ".gitignore").write_text(".autopilot/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Autopilot Test",
            "-c",
            "user.email=autopilot@example.invalid",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "pi.cmd").write_text(
        "@echo off\necho 401 Incorrect API key provided 1>&2\nexit /b 1\n",
        encoding="utf-8",
    )
    (shim_dir / "codex.cmd").write_text(
        "\n".join(
            [
                "@echo off",
                ":check_args",
                'if "%~1"=="" goto plan',
                'if "%~1"=="--ask-for-approval" exit /b 2',
                "shift",
                "goto check_args",
                ":plan",
                "if not exist .autopilot mkdir .autopilot",
                "echo task title> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo docs/operations/> .autopilot\\allowed-paths.txt",
                "echo test commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            powershell,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "autopilot.ps1"),
            "-RepoRoot",
            str(repo),
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUN: codex planner" in result.stdout
    assert "Autopilot run finished." in result.stdout
