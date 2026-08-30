from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLINK_MANIFEST = "src/agentflow_runtime/processing/flink_jobs/requirements.txt"
STALE_FLINK_MANIFEST = "src/processing/flink_jobs/requirements.txt"
_MANIFEST_LOADERS = frozenset(
    {
        "load_requirements",
        "load_project_dependencies",
        "load_optional_dependencies",
    }
)


def _load_security_workflow() -> dict:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "security.yml"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def _extract_inventory_python() -> str:
    workflow = _load_security_workflow()
    resolve_step = next(
        (
            step
            for step in workflow["jobs"]["safety"]["steps"]
            if step.get("name") == "Resolve Safety dependency inputs"
        ),
        None,
    )
    assert resolve_step is not None
    run_script = resolve_step["run"]
    _, marker, inline_python = run_script.partition("python - <<'PY'\n")
    assert marker
    inline_python, marker, _ = inline_python.partition("\nPY")
    assert marker
    return inline_python


def _posix_path_from_root_div(node: ast.AST) -> str | None:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        right = current.right
        if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
            return None
        parts.append(right.value)
        current = current.left
    if isinstance(current, ast.Name) and current.id == "root":
        return "/".join(reversed(parts))
    return None


def _inventory_manifest_paths() -> list[str]:
    tree = ast.parse(_extract_inventory_python())
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id not in _MANIFEST_LOADERS:
            continue
        assert node.args, f"{func.id} is missing a manifest path argument"
        rel = _posix_path_from_root_div(node.args[0])
        assert rel is not None, f"could not resolve manifest path for {func.id}"
        found.append(rel)
    return list(dict.fromkeys(found))


def _inventory_helpers(output_dir: Path) -> dict[str, Any]:
    tree = ast.parse(_extract_inventory_python())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    module = ast.Module(body=functions, type_ignores=[])
    namespace: dict[str, Any] = {
        "os": os,
        "subprocess": subprocess,
        "sys": sys,
        "tempfile": tempfile,
        "Path": Path,
        "tomllib": tomllib,
        "output_dir": output_dir,
        "root": PROJECT_ROOT,
    }
    exec(  # noqa: S102  # AST-compiled workflow helpers; inputs not user-controlled
        compile(module, filename="<security-workflow-inventory>", mode="exec"),
        namespace,
    )
    return namespace


def _tracked_paths(rel_paths: list[str]) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", *rel_paths],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.replace("\\", "/") for line in completed.stdout.splitlines() if line}


def test_inventory_manifest_paths_are_tracked_nonempty_files() -> None:
    manifests = _inventory_manifest_paths()
    assert manifests
    assert "pyproject.toml" in manifests
    assert "requirements.txt" in manifests
    assert "sdk/pyproject.toml" in manifests
    assert "integrations/pyproject.toml" in manifests
    assert FLINK_MANIFEST in manifests

    untracked = sorted(set(manifests) - _tracked_paths(manifests))
    assert untracked == [], f"inventory manifests are not tracked: {untracked}"

    for rel in manifests:
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        assert text.strip(), f"{rel} is empty"


def test_flink_inventory_uses_post_namespace_manifest() -> None:
    manifests = _inventory_manifest_paths()
    assert FLINK_MANIFEST in manifests
    assert STALE_FLINK_MANIFEST not in manifests
    assert STALE_FLINK_MANIFEST not in _extract_inventory_python()


def test_missing_required_manifest_does_not_silently_become_empty(
    tmp_path: Path,
) -> None:
    helpers = _inventory_helpers(tmp_path)
    missing_requirements = tmp_path / "missing-requirements.txt"
    missing_pyproject = tmp_path / "pyproject.toml"

    with pytest.raises(SystemExit, match="missing"):
        helpers["load_requirements"](missing_requirements)
    with pytest.raises(SystemExit, match="missing"):
        helpers["load_project_dependencies"](missing_pyproject)
    with pytest.raises(SystemExit, match="missing"):
        helpers["load_optional_dependencies"](missing_pyproject, "cloud")


def test_missing_required_extra_does_not_silently_become_empty(tmp_path: Path) -> None:
    helpers = _inventory_helpers(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'demo'\nversion = '0'\n\n[project.optional-dependencies]\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="cloud"):
        helpers["load_optional_dependencies"](pyproject, "cloud")


def test_required_buckets_cannot_silently_resolve_to_zero_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers = _inventory_helpers(tmp_path)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if len(command) >= 2 and command[-2:] == ["pip", "freeze"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="zero packages"):
        helpers["resolve_requirements"]("main", [], tmp_path / "requirements-main.txt")
    with pytest.raises(SystemExit, match="zero packages"):
        helpers["resolve_requirements"](
            "extra-cloud",
            ["boto3>=1.35,<2"],
            tmp_path / "requirements-extra-cloud.txt",
        )
    with pytest.raises(SystemExit, match="zero packages"):
        helpers["resolve_requirements"](
            "flink-runtime",
            ["apache-flink==2.3.0"],
            tmp_path / "requirements-flink-runtime.txt",
        )
