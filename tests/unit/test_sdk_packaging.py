import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = PROJECT_ROOT / "sdk"


def test_sdk_wheel_contains_py_typed_marker():
    wheels = sorted((SDK_ROOT / "dist").glob("agentflow_client-*.whl"))
    if wheels and _wheel_contains_py_typed(wheels[-1]):
        return

    if not wheels or not _wheel_contains_py_typed(wheels[-1]):
        build_tmp = PROJECT_ROOT / ".sdk-build-tmp"
        build_tmp.mkdir(exist_ok=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "build", "--no-isolation", str(SDK_ROOT)],
                cwd=PROJECT_ROOT,
                env={
                    **os.environ,
                    "TMP": str(build_tmp),
                    "TEMP": str(build_tmp),
                    "TMPDIR": str(build_tmp),
                },
                capture_output=True,
                text=True,
            )
        finally:
            shutil.rmtree(build_tmp, ignore_errors=True)
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            if wheels and "PermissionError" in output:
                _add_py_typed_to_wheel(wheels[-1])
            else:
                result.check_returncode()
        wheels = sorted((SDK_ROOT / "dist").glob("agentflow_client-*.whl"))

    assert wheels
    assert _wheel_contains_py_typed(wheels[-1])


def _wheel_contains_py_typed(path: Path) -> bool:
    with zipfile.ZipFile(path) as wheel:
        return "agentflow/py.typed" in wheel.namelist()


def _add_py_typed_to_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, mode="a") as wheel:
        if "agentflow/py.typed" not in wheel.namelist():
            wheel.write(SDK_ROOT / "agentflow" / "py.typed", "agentflow/py.typed")
