#!/usr/bin/env python3
"""
Bump version, create git tag, trigger CI publish.

Usage:
  python scripts/release.py patch   # 1.0.0 -> 1.0.1
  python scripts/release.py minor   # 1.0.0 -> 1.1.0
  python scripts/release.py major   # 1.0.0 -> 2.0.0
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_PYPROJECT_PATH = ROOT / "pyproject.toml"
SDK_PYPROJECT_PATH = ROOT / "sdk" / "pyproject.toml"
PACKAGE_JSON_PATH = ROOT / "sdk-ts" / "package.json"
PACKAGE_LOCK_PATH = ROOT / "sdk-ts" / "package-lock.json"
INIT_PATH = ROOT / "sdk" / "agentflow" / "__init__.py"
CHANGELOG_PATHS = (
    ROOT / "CHANGELOG.md",
    ROOT / "sdk" / "CHANGELOG.md",
    ROOT / "sdk-ts" / "CHANGELOG.md",
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
INIT_VERSION_RE = re.compile(r'(?m)^__version__ = "([^"]+)"$')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an AgentFlow SDK release.")
    parser.add_argument("part", choices=("patch", "minor", "major"))
    return parser.parse_args()


def read_versions() -> dict[str, str]:
    root_pyproject = tomllib.loads(ROOT_PYPROJECT_PATH.read_text(encoding="utf-8"))
    sdk_pyproject = tomllib.loads(SDK_PYPROJECT_PATH.read_text(encoding="utf-8"))
    package_json = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    package_lock = json.loads(PACKAGE_LOCK_PATH.read_text(encoding="utf-8"))
    init_match = INIT_VERSION_RE.search(INIT_PATH.read_text(encoding="utf-8"))
    if init_match is None:
        raise SystemExit(f"Could not find __version__ in {INIT_PATH}")
    try:
        package_lock_root_version = package_lock["packages"][""]["version"]
    except (KeyError, TypeError) as exc:
        raise SystemExit(f"Could not find root package version in {PACKAGE_LOCK_PATH}") from exc
    return {
        "pyproject.toml": root_pyproject["project"]["version"],
        "sdk/pyproject.toml": sdk_pyproject["project"]["version"],
        "sdk/agentflow/__init__.py": init_match.group(1),
        "sdk-ts/package.json": package_json["version"],
        "sdk-ts/package-lock.json": package_lock["version"],
        'sdk-ts/package-lock.json#packages[""]': package_lock_root_version,
    }


def ensure_versions_match(versions: Mapping[str, str]) -> str:
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        details = ", ".join(f"{path}={version}" for path, version in versions.items())
        raise SystemExit(f"Version mismatch detected. {details}")
    version = next(iter(unique_versions))
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"Unsupported version format: {version}")
    return version


def bump_version(current_version: str, part: str) -> str:
    major, minor, patch = (int(value) for value in current_version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def replace_version(path: Path, pattern: re.Pattern[str], new_version: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(
        lambda match: match.group(0).replace(match.group(1), new_version, 1),
        original,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"Could not update version in {path}")
    path.write_text(updated, encoding="utf-8", newline="\n")


def replace_package_json_version(path: Path, new_version: str) -> None:
    package_json = json.loads(path.read_text(encoding="utf-8"))
    package_json["version"] = new_version
    path.write_text(json.dumps(package_json, indent=2) + "\n", encoding="utf-8", newline="\n")


def replace_package_lock_version(path: Path, new_version: str) -> None:
    package_lock = json.loads(path.read_text(encoding="utf-8"))
    try:
        package_lock["version"] = new_version
        package_lock["packages"][""]["version"] = new_version
    except (KeyError, TypeError) as exc:
        raise SystemExit(f"Could not update root package version in {path}") from exc
    path.write_text(json.dumps(package_lock, indent=2) + "\n", encoding="utf-8", newline="\n")


def update_release_versions(new_version: str) -> None:
    replace_version(ROOT_PYPROJECT_PATH, PYPROJECT_VERSION_RE, new_version)
    replace_version(SDK_PYPROJECT_PATH, PYPROJECT_VERSION_RE, new_version)
    replace_version(INIT_PATH, INIT_VERSION_RE, new_version)
    replace_package_json_version(PACKAGE_JSON_PATH, new_version)
    replace_package_lock_version(PACKAGE_LOCK_PATH, new_version)


def update_changelog(path: Path, new_version: str) -> None:
    changelog = path.read_text(encoding="utf-8")
    heading = f"## [{new_version}] - {date.today().isoformat()}"
    if heading in changelog:
        raise SystemExit(f"Changelog entry already exists for {new_version}")

    marker = "## ["
    index = changelog.find(marker)
    if index == -1:
        raise SystemExit(f"Could not find insertion point in {path}")

    new_entry = f"{heading}\n\n### Changed\n- Release {new_version}.\n\n"
    updated = changelog[:index] + new_entry + changelog[index:]
    path.write_text(updated, encoding="utf-8", newline="\n")


def update_changelogs(new_version: str) -> None:
    for path in CHANGELOG_PATHS:
        update_changelog(path, new_version)


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_tag_absent(tag_name: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise SystemExit(f"Tag already exists: {tag_name}")


def commit_and_tag(new_version: str) -> None:
    files_to_stage = [
        "pyproject.toml",
        "CHANGELOG.md",
        "sdk/pyproject.toml",
        "sdk-ts/package.json",
        "sdk-ts/package-lock.json",
        "sdk/agentflow/__init__.py",
        "sdk/CHANGELOG.md",
        "sdk-ts/CHANGELOG.md",
    ]
    run_git("add", "--", *files_to_stage)
    run_git("commit", "-m", f"release: v{new_version}")
    run_git("tag", f"sdk-v{new_version}")


def main() -> int:
    args = parse_args()
    current_version = ensure_versions_match(read_versions())
    next_version = bump_version(current_version, args.part)
    ensure_tag_absent(f"sdk-v{next_version}")

    update_release_versions(next_version)
    update_changelogs(next_version)
    commit_and_tag(next_version)

    print(f"Released version {next_version}")
    print(f"Created commit: release: v{next_version}")
    print(f"Created tag: sdk-v{next_version}")
    print("Next steps:")
    print("  git push")
    print("  git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
