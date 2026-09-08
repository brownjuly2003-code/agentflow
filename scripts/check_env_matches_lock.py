#!/usr/bin/env python3
"""Check the active Python environment against the frozen project contract.

The check is deliberately read-only and offline. ``uv sync --check`` owns the
lock/profile/marker comparison; this script additionally catches stale local
editable metadata for repository packages that are installed outside the root
``uv.lock`` profile.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the active interpreter against uv.lock without changing it."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing uv.lock (default: parent of scripts/)",
    )
    parser.add_argument(
        "--uv",
        help="uv executable; intended for hermetic tests (default: resolve uv on PATH)",
    )
    return parser


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
    )


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _inside(location: Path, root: Path) -> bool:
    try:
        location.relative_to(root)
    except ValueError:
        return False
    return True


def _editable_problems(project_root: Path, installed_output: str) -> tuple[list[str], list[Path]]:
    try:
        installed: Any = json.loads(installed_output)
    except json.JSONDecodeError as exc:
        return [f"uv returned invalid editable-package JSON: {exc}"], []
    if not isinstance(installed, list):
        return ["uv editable-package output is not a JSON list"], []

    problems: list[str] = []
    repairs: list[Path] = []
    for item in installed:
        if not isinstance(item, dict):
            problems.append("uv editable-package output contains a non-object entry")
            continue
        raw_location = item.get("editable_project_location")
        if not isinstance(raw_location, str) or not raw_location:
            continue
        location = Path(raw_location)
        if not location.is_absolute():
            location = project_root / location
        location = location.resolve()
        if not _inside(location, project_root):
            continue

        metadata_path = location / "pyproject.toml"
        if not metadata_path.is_file():
            problems.append(f"editable {location} has no pyproject.toml")
            repairs.append(location)
            continue
        try:
            project = tomllib.loads(metadata_path.read_text(encoding="utf-8"))["project"]
            expected_name = str(project["name"])
            expected_version = str(project["version"])
        except (KeyError, OSError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"cannot read editable metadata from {metadata_path}: {exc}")
            repairs.append(location)
            continue

        installed_name = str(item.get("name", ""))
        installed_version = str(item.get("version", ""))
        relative = location.relative_to(project_root) or Path(".")
        if _canonical_name(installed_name) != _canonical_name(expected_name):
            problems.append(
                f"editable {relative}: installed name {installed_name}; "
                f"workspace metadata declares {expected_name}"
            )
            repairs.append(location)
        if installed_version != expected_version:
            problems.append(
                f"editable {relative} ({expected_name}): installed {installed_version}; "
                f"workspace metadata declares {expected_version}"
            )
            repairs.append(location)

    return problems, repairs


def _run(
    runner: Runner,
    command: list[str],
    *,
    project_root: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=project_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    uv = args.uv or shutil.which("uv")
    if not uv:
        print("Environment preflight FAILED: uv is not available on PATH.")
        print("Install the repository-pinned uv==0.8.23, then rerun this command.")
        return 2

    environment = os.environ.copy()
    environment["VIRTUAL_ENV"] = str(Path(sys.prefix).resolve())
    python = str(Path(sys.executable).resolve())
    lock_command = [
        uv,
        "sync",
        "--active",
        "--all-extras",
        "--frozen",
        "--check",
        "--offline",
        "--inexact",
        "--python",
        python,
    ]
    lock_result = _run(
        runner,
        lock_command,
        project_root=project_root,
        environment=environment,
    )

    editable_command = [
        uv,
        "pip",
        "list",
        "--python",
        python,
        "--editable",
        "--format",
        "json",
    ]
    editable_result = _run(
        runner,
        editable_command,
        project_root=project_root,
        environment=environment,
    )

    problems: list[str] = []
    repair_locations: list[Path] = []
    if lock_result.returncode != 0:
        detail = _combined_output(lock_result) or "uv sync --check exited without details"
        problems.append(f"locked dependency drift:\n{detail}")
    if editable_result.returncode != 0:
        detail = _combined_output(editable_result) or "uv pip list exited without details"
        problems.append(f"could not inspect editable workspace packages:\n{detail}")
    else:
        editable_problems, repair_locations = _editable_problems(
            project_root, editable_result.stdout
        )
        problems.extend(editable_problems)

    if not problems:
        print(
            f"Environment preflight OK: {python} matches uv.lock and editable workspace metadata."
        )
        return 0

    print(f"Environment preflight FAILED for {python}:")
    for problem in problems:
        lines = problem.splitlines() or [problem]
        print(f"- {lines[0]}")
        for line in lines[1:]:
            print(f"  {line}")
    print("Repair the active environment, then rerun the preflight:")
    print("  uv sync --active --all-extras --frozen --inexact")
    for location in sorted(set(repair_locations)):
        relative = location.relative_to(project_root) or Path(".")
        print(f"  uv pip install --no-deps --editable {relative}")
    print(f"  {python} scripts/check_env_matches_lock.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
