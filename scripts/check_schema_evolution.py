from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from src.serving.semantic_layer.schema_evolution import EvolutionChecker, has_version_bump


def _normalize_version(version: Any) -> str:
    normalized = str(version)
    return normalized[1:] if normalized.startswith("v") else normalized


def _version_sort_key(version: str) -> tuple[int, int | str]:
    normalized = _normalize_version(version)
    return (0, int(normalized)) if normalized.isdigit() else (1, normalized)


def _run_git(repo_root: Path, *args: str) -> str:
    git_executable = shutil.which("git") or "git"
    completed = subprocess.run(  # noqa: S603,S607
        [git_executable, *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _load_yaml(text: str) -> dict[str, Any]:
    payload = yaml.safe_load(text) or {}
    if "version" in payload:
        payload["version"] = _normalize_version(payload["version"])
    return payload


def _load_previous_contracts(
    repo_root: Path,
    base_ref: str,
    contracts_dir: Path,
) -> dict[str, dict[str, Any]]:
    previous_contracts: dict[str, dict[str, Any]] = {}
    try:
        output = _run_git(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            base_ref,
            "--",
            str(contracts_dir),
        )
    except subprocess.CalledProcessError:
        return previous_contracts
    for relative_path in output.splitlines():
        if not relative_path.endswith(".yaml"):
            continue
        content = _run_git(repo_root, "show", f"{base_ref}:{relative_path}")
        payload = _load_yaml(content)
        previous_contracts[relative_path] = payload
    return previous_contracts


def _load_current_contracts(repo_root: Path, contracts_dir: Path) -> dict[str, dict[str, Any]]:
    current_contracts: dict[str, dict[str, Any]] = {}
    for path in sorted((repo_root / contracts_dir).glob("*.yaml")):
        relative_path = path.relative_to(repo_root).as_posix()
        current_contracts[relative_path] = _load_yaml(path.read_text(encoding="utf-8"))
    return current_contracts


def _group_by_entity(contracts: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for payload in contracts.values():
        entity = payload.get("entity")
        version = payload.get("version")
        if entity is None or version is None:
            continue
        grouped.setdefault(str(entity), []).append(payload)
    for payloads in grouped.values():
        payloads.sort(key=lambda item: _version_sort_key(str(item["version"])))
    return grouped


def find_breaking_changes_without_version_bump(
    previous_contracts: dict[str, dict[str, Any]],
    current_contracts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    checker = EvolutionChecker()
    previous_by_entity = _group_by_entity(previous_contracts)
    violations: list[dict[str, Any]] = []

    for path, current_schema in sorted(current_contracts.items()):
        entity = current_schema.get("entity")
        version = current_schema.get("version")
        if entity is None or version is None:
            continue

        previous_schema = previous_contracts.get(path)
        if previous_schema is None:
            entity_history = previous_by_entity.get(str(entity), [])
            if not entity_history:
                continue
            previous_schema = entity_history[-1]

        report = checker.check(previous_schema, current_schema)
        if not report.is_breaking:
            continue
        if has_version_bump(previous_schema, current_schema):
            continue

        violations.append({
            "path": path,
            "entity": entity,
            "base_version": previous_schema.get("version"),
            "candidate_version": current_schema.get("version"),
            "breaking_changes": report.breaking_changes,
        })

    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--contracts-dir", default="config/contracts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path.cwd()
    contracts_dir = Path(args.contracts_dir)

    previous_contracts = _load_previous_contracts(repo_root, args.base_ref, contracts_dir)
    current_contracts = _load_current_contracts(repo_root, contracts_dir)
    violations = find_breaking_changes_without_version_bump(
        previous_contracts,
        current_contracts,
    )

    if not violations:
        print("Schema evolution check passed.")
        return 0

    for violation in violations:
        print(
            (
                f"Breaking schema change without version bump in {violation['path']} "
                f"({violation['entity']} {violation['base_version']} -> "
                f"{violation['candidate_version']}): {violation['breaking_changes']}"
            ),
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
