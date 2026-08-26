"""Structural contract for the isolated OpsLab distribution."""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

OPSLAB_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = OPSLAB_ROOT / "src" / "agentflow_opslab"

REQUIRED_CORE_AREAS = (
    "domain",
    "contracts",
    "ports",
)
CORE_AREAS = REQUIRED_CORE_AREAS + (
    "scenario",
    "observation",
    "action",
    "evidence",
    "verification",
    "application",
)
FORBIDDEN_CORE_IMPORTS = frozenset(
    {
        "agentflow_runtime",
        "src",
        "fastapi",
        "duckdb",
        "confluent_kafka",
        "httpx",
        "mcp",
        "a2a",
    }
)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def test_distribution_metadata_declares_isolated_package() -> None:
    metadata = tomllib.loads((OPSLAB_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "agentflow-opslab"
    assert metadata["project"]["requires-python"] == ">=3.11"
    wheel = metadata["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/agentflow_opslab"]


def test_package_imports_without_loading_legacy_runtime() -> None:
    probe = """
import importlib
import pathlib
import sys

source_root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source_root))
module = importlib.import_module("agentflow_opslab")
module_path = pathlib.Path(module.__file__).resolve()
assert module_path.is_relative_to(source_root)
assert "agentflow_runtime" not in sys.modules
assert "src" not in sys.modules
"""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", probe, str(OPSLAB_ROOT / "src")],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_core_never_imports_runtime_storage_or_transport() -> None:
    assert PACKAGE_ROOT.is_dir(), "the isolated agentflow_opslab package is missing"
    for area in REQUIRED_CORE_AREAS:
        assert (PACKAGE_ROOT / area / "__init__.py").is_file(), (
            f"required transport-neutral core area is missing: {area}"
        )
    offenders: dict[str, list[str]] = {}
    for area in CORE_AREAS:
        area_root = PACKAGE_ROOT / area
        if not area_root.exists():
            continue
        for path in sorted(area_root.rglob("*.py")):
            forbidden = sorted(_import_roots(path) & FORBIDDEN_CORE_IMPORTS)
            if forbidden:
                offenders[path.relative_to(OPSLAB_ROOT).as_posix()] = forbidden
    assert not offenders, f"OpsLab core crossed its dependency boundary: {offenders}"
