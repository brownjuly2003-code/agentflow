from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _powershell() -> str:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell is not None
    return powershell


def _write_shim(shim_dir: Path, name: str, cmd_script: str, sh_script: str) -> None:
    if os.name == "nt":
        (shim_dir / f"{name}.cmd").write_text(cmd_script, encoding="utf-8")
        return

    target = shim_dir / name
    target.write_text("#!/usr/bin/env sh\n" + sh_script, encoding="utf-8")
    target.chmod(0o755)


def _ensure_windows_powershell_command(shim_dir: Path, powershell: str) -> None:
    if os.name == "nt" or shutil.which("powershell"):
        return

    target = shim_dir / "powershell"
    target.write_text(f'#!/usr/bin/env sh\nexec "{powershell}" "$@"\n', encoding="utf-8")
    target.chmod(0o755)


def test_autopilot_accepts_clean_worktree_with_no_initial_changes(tmp_path):
    powershell = _powershell()

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
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(
        shim_dir,
        "pi",
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
        "\n".join(
            [
                "mkdir -p .autopilot",
                "echo task title> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo docs/operations/> .autopilot/allowed-paths.txt",
                "echo test commit> .autopilot/commit-message.txt",
                "exit 0",
            ]
        ),
    )
    _write_shim(
        shim_dir,
        "codex",
        "@echo off\n"
        ":check_args\n"
        'if "%~1"=="" goto done\n'
        'if "%~1"=="--ask-for-approval" exit /b 2\n'
        "shift\n"
        "goto check_args\n"
        ":done\n"
        "exit /b 0\n",
        "\n".join(
            [
                'for arg in "$@"; do',
                '  if [ "$arg" = "--ask-for-approval" ]; then exit 2; fi',
                "done",
                "exit 0",
            ]
        ),
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
    powershell = _powershell()

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
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(
        shim_dir,
        "pi",
        "@echo off\necho 401 Incorrect API key provided 1>&2\nexit /b 1\n",
        'echo "401 Incorrect API key provided" >&2\nexit 1\n',
    )
    _write_shim(
        shim_dir,
        "codex",
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
        "\n".join(
            [
                'for arg in "$@"; do',
                '  if [ "$arg" = "--ask-for-approval" ]; then exit 2; fi',
                "done",
                "mkdir -p .autopilot",
                "echo task title> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo docs/operations/> .autopilot/allowed-paths.txt",
                "echo test commit> .autopilot/commit-message.txt",
                "exit 0",
            ]
        ),
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
