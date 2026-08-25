"""`AGENTFLOW_SRC_SHIM_SILENT` is a boolean, not a presence check (audit F-15).

The shim's own docstring and `docs/migration/v2.1.md` both document
`AGENTFLOW_SRC_SHIM_SILENT=1`, while the implementation only asked whether the
variable was set to anything non-empty. So `AGENTFLOW_SRC_SHIM_SILENT=0`
silenced the deprecation warning it reads as asking to keep -- a small gap, but
the shim is a deprecation contract, and a contract whose off switch fires when
you decline it is not one.

The shim is exercised as the real file: the deprecation warning is emitted at
module scope, once per process, so each case runs in its own subprocess against
a copy of `packaging/src_shim/src/__init__.py` placed where `import src` finds
it. Nothing here imports the runtime -- the aliasing is lazy, and the warning
fires before any of it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_SOURCE = REPO_ROOT / "packaging" / "src_shim" / "src" / "__init__.py"

_PROBE = """
import sys
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import src  # noqa: F401

deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
print("WARNED" if deprecations else "SILENT")
"""


@pytest.fixture(scope="module")
def shim_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory holding `src/__init__.py`, importable as a real package.

    The repository's own `src/` is a plain container with no `__init__.py`, so
    the shim cannot be imported from the tree; this stages it the way a wheel
    install does.
    """
    root = tmp_path_factory.mktemp("shim-root")
    package = root / "src"
    package.mkdir()
    shutil.copyfile(SHIM_SOURCE, package / "__init__.py")
    return root


def _import_shim(shim_root: Path, value: str | None) -> str:
    env = {
        "PATH": "",
        "SYSTEMROOT": "",
        "PYTHONPATH": str(shim_root),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if value is not None:
        env["AGENTFLOW_SRC_SHIM_SILENT"] = value

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE],
        cwd=shim_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " 1 "])
def test_true_values_silence_the_deprecation_warning(shim_root: Path, value: str):
    assert _import_shim(shim_root, value) == "SILENT"


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off"])
def test_unset_and_false_values_keep_the_warning(shim_root: Path, value: str | None):
    """`0` is the case the finding is about: it used to silence the warning."""
    assert _import_shim(shim_root, value) == "WARNED"


def test_an_unrecognised_value_warns(shim_root: Path):
    """A deprecation notice is the safe default when the intent is unclear."""
    assert _import_shim(shim_root, "banana") == "WARNED"


def test_the_documented_flag_matches_the_implementation():
    """The gap was between the docs and the code, so pin them to each other."""
    shim = SHIM_SOURCE.read_text(encoding="utf-8")
    migration = (REPO_ROOT / "docs" / "migration" / "v2.1.md").read_text(encoding="utf-8")

    assert '_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})' in shim
    assert "AGENTFLOW_SRC_SHIM_SILENT=1" in migration
    assert "parsed as a boolean" in migration
