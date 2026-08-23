"""Wheel namespace smoke for the runtime distribution (audit F-09).

Two layers, both runnable locally and in CI:

1. **Top-level policy** (always): the built wheel must ship exactly the
   declared top-level members — the ``agentflow_runtime`` package, the
   one-file deprecated ``src`` shim (``src/__init__.py`` and nothing else
   under ``src/``), and the dist-info directory. Any other top-level entry
   is an undeclared package leaking into the distribution and fails the
   check.

2. **Install smoke outside the checkout** (``--venv-smoke``): a fresh venv
   is created in the system temp directory, the wheel is installed with
   ``--no-deps``, and a subprocess running *outside the repository* proves
   that (a) ``import agentflow_runtime`` works and is warning-free,
   (b) ``import src.constants`` still works through the shim, warns with
   ``DeprecationWarning``, and yields the *same module object* as
   ``agentflow_runtime.constants``, and (c) ``AGENTFLOW_SRC_SHIM_SILENT=1``
   silences the warning. Pass ``--deps-from`` (a site-packages dir with the
   runtime's dependencies) to additionally smoke the deep
   ``src.serving.api.main`` import, mirroring the CI clean-env job.

Usage:
    python scripts/wheel_smoke.py dist/agentflow_runtime-*.whl
    python scripts/wheel_smoke.py dist/*.whl --venv-smoke \
        --deps-from .venv/Lib/site-packages
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

DIST_INFO_RE = re.compile(r"^agentflow_runtime-[^/]+\.dist-info$")
ALLOWED_TOP_LEVEL = {"agentflow_runtime", "src"}

SMOKE_SCRIPT = r"""
import os
import sys
import warnings

deps_from = os.environ.get("WHEEL_SMOKE_DEPS_FROM")
if deps_from:
    sys.path.append(deps_from)

with warnings.catch_warnings():
    warnings.simplefilter("error")
    import agentflow_runtime
    import agentflow_runtime.constants

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import src.constants

    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "shim import produced no DeprecationWarning"

assert (
    src.constants is agentflow_runtime.constants
), "src.constants is not the same module object as agentflow_runtime.constants"
assert agentflow_runtime.constants.__name__ == "agentflow_runtime.constants", (
    "shim aliasing renamed the real module: " + agentflow_runtime.constants.__name__
)

if deps_from:
    from src.serving.api.main import app as shim_app
    from agentflow_runtime.serving.api.main import app as real_app

    assert shim_app is real_app, "deep shim import returned a different app object"

print("wheel smoke imports OK")
"""

SILENCE_SCRIPT = r"""
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import src.constants  # noqa: F401

    assert not any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "AGENTFLOW_SRC_SHIM_SILENT=1 did not silence the shim warning"

print("shim silence OK")
"""


def check_top_level(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    top_level = {name.split("/", 1)[0] for name in names}
    unexpected = {
        entry
        for entry in top_level
        if entry not in ALLOWED_TOP_LEVEL and not DIST_INFO_RE.match(entry)
    }
    if unexpected:
        raise SystemExit(
            f"{wheel.name}: undeclared top-level entries in wheel: {sorted(unexpected)}"
        )
    shim_members = [name for name in names if name.startswith("src/")]
    if shim_members != ["src/__init__.py"]:
        raise SystemExit(
            f"{wheel.name}: the src shim must be exactly ['src/__init__.py'], got {shim_members}"
        )
    if not any(name.startswith("agentflow_runtime/") for name in names):
        raise SystemExit(f"{wheel.name}: wheel does not ship the agentflow_runtime package")
    print(f"{wheel.name}: top-level policy OK ({sorted(top_level)})")


def venv_smoke(wheel: Path, deps_from: str | None) -> None:
    # tempfile.mkdtemp lives outside the checkout, so `src`/`agentflow_runtime`
    # can only resolve from the installed wheel, never from the working tree.
    tmp = Path(tempfile.mkdtemp(prefix="agentflow-wheel-smoke-"))
    venv_dir = tmp / "venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")

    def run(args: list[str], env_extra: dict[str, str]) -> None:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(env_extra)
        subprocess.run(args, check=True, cwd=tmp, env=env)  # noqa: S603

    run([str(python), "-m", "pip", "install", "--quiet", "--no-deps", str(wheel)], {})
    smoke_env = {"WHEEL_SMOKE_DEPS_FROM": deps_from} if deps_from else {}
    run([str(python), "-c", SMOKE_SCRIPT], smoke_env)
    run([str(python), "-c", SILENCE_SCRIPT], {"AGENTFLOW_SRC_SHIM_SILENT": "1"})
    print(f"{wheel.name}: venv install smoke OK (outside checkout: {tmp})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", help="path or glob to the agentflow_runtime wheel")
    parser.add_argument("--venv-smoke", action="store_true")
    parser.add_argument(
        "--deps-from",
        default=None,
        help="site-packages directory that already holds the runtime dependencies",
    )
    args = parser.parse_args()

    matches = sorted(glob.glob(args.wheel))
    runtime_wheels = [Path(m) for m in matches if Path(m).name.startswith("agentflow_runtime-")]
    if not runtime_wheels:
        raise SystemExit(f"no agentflow_runtime wheel matches {args.wheel!r}")
    wheel = runtime_wheels[-1].resolve()

    check_top_level(wheel)
    if args.venv_smoke:
        deps_from = str(Path(args.deps_from).resolve()) if args.deps_from else None
        venv_smoke(wheel, deps_from)
    return 0


if __name__ == "__main__":
    sys.exit(main())
