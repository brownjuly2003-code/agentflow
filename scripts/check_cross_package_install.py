"""Prove that the SDK and integrations wheels resolve together from scratch."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(command: Sequence[str]) -> None:
    subprocess.run(list(command), check=True, cwd=PROJECT_ROOT)  # noqa: S603


def _build_wheel(package_dir: str, wheel_prefix: str, wheelhouse: Path) -> Path:
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheelhouse),
            str(PROJECT_ROOT / package_dir),
        ]
    )
    wheels = sorted(wheelhouse.glob(f"{wheel_prefix}-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one {wheel_prefix} wheel, found {wheels}")
    return wheels[0]


def _venv_python(venv_dir: Path) -> Path:
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    return bin_dir / ("python.exe" if os.name == "nt" else "python")


def _install_and_check(python: Path, wheels: Sequence[Path]) -> None:
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            *(str(wheel) for wheel in wheels),
        ]
    )
    _run([str(python), "-m", "pip", "check"])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agentflow-cross-package-") as temporary_dir:
        temporary_path = Path(temporary_dir)
        wheelhouse = temporary_path / "wheelhouse"
        wheelhouse.mkdir()
        wheels = (
            _build_wheel("sdk", "agentflow_client", wheelhouse),
            _build_wheel("integrations", "agentflow_integrations", wheelhouse),
        )

        venv_dir = temporary_path / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        _install_and_check(_venv_python(venv_dir), wheels)

    print("CROSS_PACKAGE_INSTALL=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
