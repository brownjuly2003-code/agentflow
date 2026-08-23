"""Namespace-migration drift guard (audit F-09 / P2-6).

Since 2.1.0 the runtime package is ``agentflow_runtime`` under the plain
``src/`` container directory, and the generic ``src`` import surface exists
only as the one-file deprecated wheel shim. These tests pin the layout so
it cannot silently regress:

1. the ``src/`` container holds exactly the ``agentflow_runtime`` package —
   a new sibling there would be an undeclared top-level package that
   ``packages = ["src/agentflow_runtime"]`` silently drops from the wheel;
2. no first-party code imports the runtime through ``src.*`` any more
   (the byte-pinned golden-soak pack is the single recorded exception);
3. the packaging config keeps shipping the shim exactly as one file mapped
   to ``src/__init__.py``, and the shim keeps its deprecation contract.

The wheel itself is verified by ``scripts/wheel_smoke.py`` (top-level
policy + install smoke outside the checkout) in the python-compat CI job.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

RUNTIME_TOP_MODULES = (
    "constants",
    "db_concurrency",
    "ingestion",
    "logger",
    "orchestration",
    "processing",
    "quality",
    "serving",
    "tenancy",
    "version",
)

# Built dynamically so this file does not match its own pattern.
_SRC_DOTTED = re.compile(r"\bsrc" + r"\.(" + "|".join(RUNTIME_TOP_MODULES) + r")\b")

# Directories whose tracked *.py files must not import the runtime as src.*
FIRST_PARTY_SCAN_DIRS = ("src", "tests", "scripts", "sdk", "integrations", "warehouse")

# The golden-soak pack is byte-pinned by its MANIFEST.json; rewriting it would
# invalidate the recorded runtime identity. It executes only inside frozen
# soak packets, never from this tree.
ALLOWED_LEGACY = ("scripts/golden_soak/pack/",)

# Files that legitimately mention the deprecated surface *as data*: this
# guard itself, the wheel smoke that exercises the shim, and the CI contract
# test that pins the shim-smoke step's import line.
ALLOWED_FILES = frozenset(
    {
        "tests/unit/test_namespace_policy.py",
        "tests/unit/test_quickstart_install_contract.py",
        "scripts/wheel_smoke.py",
    }
)


def _tracked_python_files() -> list[str]:
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--", *(f"{d}/*.py" for d in FIRST_PARTY_SCAN_DIRS)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        pytest.skip("git not available; namespace scan needs the tracked file list")
    return [line for line in completed.stdout.splitlines() if line]


def test_src_container_holds_only_the_runtime_package() -> None:
    entries = sorted(p.name for p in (REPO_ROOT / "src").iterdir() if p.name != "__pycache__")
    assert entries == ["agentflow_runtime"], (
        "src/ is a plain container for the agentflow_runtime package; "
        f"unexpected entries: {entries}. A sibling here would be an undeclared "
        "top-level package that the wheel config silently drops."
    )
    assert not (REPO_ROOT / "src" / "__init__.py").exists(), (
        "src/__init__.py in the repository would turn the container into a "
        "package and shadow the wheel shim; the shim lives only in "
        "packaging/src_shim/"
    )
    for module in RUNTIME_TOP_MODULES:
        base = REPO_ROOT / "src" / "agentflow_runtime" / module
        assert base.exists() or base.with_suffix(".py").exists(), (
            f"expected runtime module missing after the namespace move: {module}"
        )


def test_no_first_party_src_imports_remain() -> None:
    offenders: list[str] = []
    for rel in _tracked_python_files():
        if any(rel.startswith(prefix) for prefix in ALLOWED_LEGACY):
            continue
        if rel in ALLOWED_FILES:
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if _SRC_DOTTED.search(text) or "from src import" in text:
            offenders.append(rel)
    assert not offenders, (
        "first-party code must import agentflow_runtime, not the deprecated "
        f"src.* surface: {offenders}"
    )


def test_wheel_packaging_ships_runtime_plus_one_file_shim() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'only-include = ["src/agentflow_runtime", "packaging/src_shim/src"]' in pyproject
    assert '"src/agentflow_runtime" = "agentflow_runtime"' in pyproject
    assert '"packaging/src_shim/src" = "src"' in pyproject


def test_shim_keeps_its_deprecation_contract() -> None:
    shim = (REPO_ROOT / "packaging" / "src_shim" / "src" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "DeprecationWarning" in shim
    assert "AGENTFLOW_SRC_SHIM_SILENT" in shim
    assert '_TARGET = "agentflow_runtime"' in shim
    shim_dir = REPO_ROOT / "packaging" / "src_shim" / "src"
    extra = sorted(p.name for p in shim_dir.iterdir() if p.name != "__init__.py")
    assert not extra, f"the src shim must stay a single __init__.py, found: {extra}"
