"""Telemetry is a required import, not a best-effort one (audit F-13).

`serving/api/main.py` used to wrap the `setup_telemetry` import in a blanket
`except ModuleNotFoundError` and substitute a no-op. OpenTelemetry is a
mandatory runtime dependency, so nothing that catch could ever catch was a
legitimate "telemetry is optional here" case: it was a packaging defect or a
broken transitive import inside the telemetry module, traded silently for an
API that boots with no tracing and says nothing about it.

Running without telemetry is supported, and has its own switch --
`OTEL_SDK_DISABLED=true`, which `setup_telemetry` honours at call time
(`tests/unit/test_telemetry.py::test_setup_telemetry_respects_otel_sdk_disabled`).
An unimportable module is a different thing and must be loud.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Deep enough in the chain that no one would reach for it deliberately: it is
# imported by the telemetry module, not by main, so blocking it reproduces the
# transitive failure rather than an obvious top-level one.
BLOCKED_MODULE = "opentelemetry.instrumentation.httpx"

_IMPORT_WITH_BLOCKED_DEPENDENCY = f"""
import sys

BLOCKED = {BLOCKED_MODULE!r}


class _Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == BLOCKED:
            raise ModuleNotFoundError(f"No module named {{fullname!r}}", name=fullname)
        return None


sys.meta_path.insert(0, _Blocker())
sys.modules.pop(BLOCKED, None)

import agentflow_runtime.serving.api.main  # noqa: F401

print("IMPORTED-WITH-TELEMETRY-SILENTLY-DISABLED")
"""


def test_api_module_binds_the_real_telemetry_setup():
    """The cheap half of the contract: whatever `main.setup_telemetry` is, it
    must be the actual implementation and not a stand-in."""
    from agentflow_runtime.serving.api import main, telemetry

    assert main.setup_telemetry is telemetry.setup_telemetry


def test_a_transitive_import_failure_is_not_swallowed():
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _IMPORT_WITH_BLOCKED_DEPENDENCY],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode != 0, (
        "importing the API with a broken telemetry dependency succeeded: the "
        f"module-level fallback is back.\n{output}"
    )
    assert "IMPORTED-WITH-TELEMETRY-SILENTLY-DISABLED" not in completed.stdout
    assert "ModuleNotFoundError" in output
    assert BLOCKED_MODULE in output


def test_opentelemetry_stays_a_mandatory_runtime_dependency():
    """The reason there is no fallback. If OpenTelemetry ever moves to an
    optional extra, this test fails and the fallback question is legitimately
    reopened -- with `exc.name` checked against the specific module, per the
    audit -- rather than the catch quietly reappearing."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = pyproject["project"]["dependencies"]
    names = {
        requirement.split(">")[0].split("<")[0].split("=")[0].strip() for requirement in required
    }

    assert "opentelemetry-sdk" in names
    assert "opentelemetry-instrumentation-fastapi" in names
    assert "opentelemetry-instrumentation-httpx" in names
    assert "opentelemetry-exporter-otlp-proto-grpc" in names


def test_main_declares_no_module_not_found_fallback():
    """A regression written as source policy as well as behaviour: the
    behavioural test above costs a subprocess, and a reviewer adding a catch
    should see it fail here first."""
    source = (REPO_ROOT / "src" / "agentflow_runtime" / "serving" / "api" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "except ModuleNotFoundError" not in source
    assert "from agentflow_runtime.serving.api.telemetry import setup_telemetry" in source
