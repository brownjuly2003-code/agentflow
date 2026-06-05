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
    subprocess.run(["git", "config", "user.name", "Autopilot Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "autopilot@example.invalid"], cwd=repo, check=True
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
        "\n".join(
            [
                "@echo off",
                ":check_args",
                'if "%~1"=="" goto done',
                'if "%~1"=="--ask-for-approval" exit /b 2',
                'if "%~1"=="--sandbox" (',
                '  if "%~2"=="danger-full-access" (',
                "    shift",
                "    shift",
                "    goto check_args",
                "  )",
                "  exit /b 3",
                ")",
                "shift",
                "goto check_args",
                ":done",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                'while [ "$#" -gt 0 ]; do',
                '  if [ "$1" = "--ask-for-approval" ]; then exit 2; fi',
                '  if [ "$1" = "--sandbox" ]; then',
                '    if [ "$2" != "danger-full-access" ]; then exit 3; fi',
                "    shift 2",
                "    continue",
                "  fi",
                "  shift",
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
            "-Planner",
            "pi",
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
                'if "%~1"=="--sandbox" (',
                '  if "%~2"=="danger-full-access" (',
                "    shift",
                "    shift",
                "    goto check_args",
                "  )",
                "  exit /b 3",
                ")",
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
                'while [ "$#" -gt 0 ]; do',
                '  if [ "$1" = "--ask-for-approval" ]; then exit 2; fi',
                '  if [ "$1" = "--sandbox" ]; then',
                '    if [ "$2" != "danger-full-access" ]; then exit 3; fi',
                "    shift 2",
                "    continue",
                "  fi",
                "  shift",
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
            "-Planner",
            "auto",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUN: codex planner" in result.stdout
    assert "Autopilot run finished." in result.stdout


def test_autopilot_clears_stale_task_handoff_before_planning(tmp_path):
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
    autopilot_dir = repo / ".autopilot"
    autopilot_dir.mkdir()
    (autopilot_dir / "NEXT_TASK.md").write_text(
        "stale task\ncommit allowed: no\n", encoding="utf-8"
    )
    (autopilot_dir / "allowed-paths.txt").write_text("docs/\n", encoding="utf-8")
    (autopilot_dir / "commit-message.txt").write_text("stale commit\n", encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 0\n", "exit 0\n")
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 0\n", "exit 0\n")

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
            "-Planner",
            "pi",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Planner did not create .autopilot/NEXT_TASK.md" in result.stdout


def test_autopilot_blocks_repeated_task_fingerprint(tmp_path):
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
                "echo repeated task> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo docs/operations/> .autopilot\\allowed-paths.txt",
                "echo repeated commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                "mkdir -p .autopilot",
                "echo repeated task> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo docs/operations/> .autopilot/allowed-paths.txt",
                "echo repeated commit> .autopilot/commit-message.txt",
                "exit 0",
            ]
        ),
    )
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 0\n", "exit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    command = [
        powershell,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROJECT_ROOT / "scripts" / "autopilot.ps1"),
        "-RepoRoot",
        str(repo),
        "-Planner",
        "pi",
    ]

    first = subprocess.run(command, env=env, capture_output=True, text=True)
    second = subprocess.run(command, env=env, capture_output=True, text=True)

    assert first.returncode == 0, first.stdout + first.stderr
    assert "Autopilot run finished." in first.stdout
    assert second.returncode == 1
    assert "same task fingerprint" in second.stdout


def test_autopilot_planner_prompt_allows_bounded_product_code():
    script = (PROJECT_ROOT / "scripts" / "autopilot.ps1").read_text(encoding="utf-8")

    assert "- Do not edit product code." not in script
    assert "Product code is allowed only for bounded local tasks" in script


def test_autopilot_planner_prompt_blocks_head_only_handoff_churn():
    script = (PROJECT_ROOT / "scripts" / "autopilot.ps1").read_text(encoding="utf-8")

    assert "Do not choose handoff refresh solely to update HEAD" in script
    assert "documentation churn only to keep the autopilot moving" in script


def test_autopilot_runs_python_gates_for_warehouse_changes(tmp_path):
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
    python_log = tmp_path / "python.log"
    shim_dir.mkdir()
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(
        shim_dir,
        "pi",
        "\n".join(
            [
                "@echo off",
                "if not exist .autopilot mkdir .autopilot",
                "echo warehouse task> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo warehouse/> .autopilot\\allowed-paths.txt",
                "echo warehouse commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                "mkdir -p .autopilot",
                "echo warehouse task> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo warehouse/> .autopilot/allowed-paths.txt",
                "echo warehouse commit> .autopilot/commit-message.txt",
                "exit 0",
            ]
        ),
    )
    _write_shim(
        shim_dir,
        "codex",
        "\n".join(
            [
                "@echo off",
                "if not exist warehouse mkdir warehouse",
                "echo VALUE = 1> warehouse\\example.py",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                "mkdir -p warehouse",
                "echo 'VALUE = 1' > warehouse/example.py",
                "exit 0",
            ]
        ),
    )
    _write_shim(
        shim_dir,
        "python",
        "\n".join(
            [
                "@echo off",
                f'echo %*>> "{python_log}"',
                'if "%~1"=="-m" if "%~2"=="mypy" if "%~3"=="--version" exit /b 1',
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                f'printf "%s\\n" "$*" >> "{python_log}"',
                'if [ "$1" = "-m" ] && [ "$2" = "mypy" ] && [ "$3" = "--version" ]; then',
                "  exit 1",
                "fi",
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
            "-Planner",
            "pi",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    python_calls = python_log.read_text(encoding="utf-8")
    # The pytest gate must run the canonical no-Docker broad slice (the
    # local-verification-matrix form), not a bare full-repo run: the full
    # run needs Docker services, and the scheduled host environment does
    # not guarantee them.
    assert "-m pytest tests/unit -p no:schemathesis --continue-on-collection-errors" in python_calls
    assert "-m ruff check warehouse/example.py" in python_calls
    assert "SKIP_DOCKER_TESTS='1'" in result.stdout


def test_autopilot_defaults_to_codex_planner_without_running_pi(tmp_path):
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
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(
        shim_dir,
        "codex",
        "\n".join(
            [
                "@echo off",
                ":check_args",
                'if "%~1"=="" goto plan',
                'if "%~1"=="--sandbox" (',
                '  if "%~2"=="danger-full-access" (',
                "    shift",
                "    shift",
                "    goto check_args",
                "  )",
                "  exit /b 3",
                ")",
                "shift",
                "goto check_args",
                ":plan",
                "if not exist .autopilot mkdir .autopilot",
                "echo codex task> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo docs/operations/> .autopilot\\allowed-paths.txt",
                "echo codex commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                'while [ "$#" -gt 0 ]; do',
                '  if [ "$1" = "--sandbox" ]; then',
                '    if [ "$2" != "danger-full-access" ]; then exit 3; fi',
                "    shift 2",
                "    continue",
                "  fi",
                "  shift",
                "done",
                "mkdir -p .autopilot",
                "echo codex task> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo docs/operations/> .autopilot/allowed-paths.txt",
                "echo codex commit> .autopilot/commit-message.txt",
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
    assert "RUN: pi planner" not in result.stdout
    assert "RUN: codex planner" in result.stdout
    assert "Autopilot run finished." in result.stdout


def test_autopilot_commit_gate_accepts_markdown_section_format(tmp_path):
    powershell = _powershell()

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / ".gitignore").write_text(".autopilot/\n", encoding="utf-8")
    (repo / "state.md").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "state.md"], cwd=repo, check=True)
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
    subprocess.run(["git", "config", "user.name", "Autopilot Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "autopilot@example.invalid"], cwd=repo, check=True
    )

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(
        shim_dir,
        "codex",
        "\n".join(
            [
                "@echo off",
                ":check_args",
                'if "%~1"=="" goto plan_or_execute',
                "shift",
                "goto check_args",
                ":plan_or_execute",
                "if exist .autopilot\\NEXT_TASK.md goto execute",
                "if not exist .autopilot mkdir .autopilot",
                "echo # Task> .autopilot\\NEXT_TASK.md",
                "echo ## Commit Allowed>> .autopilot\\NEXT_TASK.md",
                "echo yes>> .autopilot\\NEXT_TASK.md",
                "echo state.md> .autopilot\\allowed-paths.txt",
                "echo docs: update state> .autopilot\\commit-message.txt",
                "exit /b 0",
                ":execute",
                "echo new> state.md",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                'while [ "$#" -gt 0 ]; do shift; done',
                "mkdir -p .autopilot",
                "if [ -f .autopilot/NEXT_TASK.md ]; then",
                "  echo new > state.md",
                "  exit 0",
                "fi",
                "echo '# Task' > .autopilot/NEXT_TASK.md",
                "echo '## Commit Allowed' >> .autopilot/NEXT_TASK.md",
                "echo 'yes' >> .autopilot/NEXT_TASK.md",
                "echo state.md > .autopilot/allowed-paths.txt",
                "echo 'docs: update state' > .autopilot/commit-message.txt",
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
            "-Commit",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Committed verified autopilot changes." in result.stdout
    assert not (repo / ".autopilot" / "BLOCKED.md").exists()


def test_autopilot_exit_zero_on_existing_blocked_when_requested(tmp_path):
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
    autopilot_dir = repo / ".autopilot"
    autopilot_dir.mkdir()
    (autopilot_dir / "BLOCKED.md").write_text("no safe task\n", encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 0\n", "exit 0\n")

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
            "-ExitZeroOnBlocked",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "BLOCKED.md exists; exiting without work." in result.stdout


def test_install_autopilot_task_uses_exit_zero_on_blocked_by_default():
    script = (PROJECT_ROOT / "scripts" / "install-autopilot-task.ps1").read_text(encoding="utf-8")

    assert "-ExitZeroOnBlocked" in script
    assert '-File `"$RunnerPath`" -Planner $Planner -ExitZeroOnBlocked' in script


def test_autopilot_exits_without_blocking_when_active_lock_exists(tmp_path):
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
    autopilot_dir = repo / ".autopilot"
    autopilot_dir.mkdir()
    (autopilot_dir / "autopilot.lock").write_text(
        f"pid={os.getpid()}\nstarted=2026-05-29T06:54:30\n",
        encoding="utf-8",
    )

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _ensure_windows_powershell_command(shim_dir, powershell)
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 0\n", "exit 0\n")
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 0\n", "exit 0\n")

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
    assert "another autopilot run is active" in result.stdout
    assert not (autopilot_dir / "BLOCKED.md").exists()


def test_autopilot_claude_planner_and_executor(tmp_path):
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
    # pi and codex must NOT run when -Planner claude is selected
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(
        shim_dir,
        "claude",
        "\n".join(
            [
                "@echo off",
                "if not exist .autopilot mkdir .autopilot",
                "echo claude task> .autopilot\\NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot\\NEXT_TASK.md",
                "echo docs/operations/> .autopilot\\allowed-paths.txt",
                "echo claude commit> .autopilot\\commit-message.txt",
                "exit /b 0",
            ]
        ),
        "\n".join(
            [
                "mkdir -p .autopilot",
                "echo claude task> .autopilot/NEXT_TASK.md",
                "echo commit allowed: no>> .autopilot/NEXT_TASK.md",
                "echo docs/operations/> .autopilot/allowed-paths.txt",
                "echo claude commit> .autopilot/commit-message.txt",
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
            "-Planner",
            "claude",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUN: claude planner" in result.stdout
    assert "RUN: claude executor" in result.stdout
    assert "RUN: pi planner" not in result.stdout
    assert "RUN: codex planner" not in result.stdout
    assert "Autopilot run finished." in result.stdout


def test_autopilot_claude_planner_failure_blocks(tmp_path):
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
    # pi and codex must NOT run when -Planner claude is selected
    _write_shim(shim_dir, "pi", "@echo off\nexit /b 9\n", "exit 9\n")
    _write_shim(shim_dir, "codex", "@echo off\nexit /b 9\n", "exit 9\n")
    # claude planner dies non-zero WITHOUT writing .autopilot/NEXT_TASK.md
    _write_shim(shim_dir, "claude", "@echo off\nexit /b 1\n", "exit 1\n")

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
            "-Planner",
            "claude",
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    blocked = repo / ".autopilot" / "BLOCKED.md"
    assert blocked.exists(), result.stdout + result.stderr
    assert "claude planner failed" in blocked.read_text(encoding="utf-8")
    assert "RUN: pi planner" not in result.stdout
    assert "RUN: codex planner" not in result.stdout
