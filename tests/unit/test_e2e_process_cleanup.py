"""C-5: the e2e conftest must reap orphaned local uvicorn children.

The e2e session fixture starts uvicorn via ``subprocess.Popen``; on an abrupt
pytest exit the normal teardown never runs, so a process registry plus an
``atexit`` / ``pytest_sessionfinish`` backstop must terminate any tracked
child. Otherwise the orphan keeps holding ``agentflow-api.log`` and the next
run's temp cleanup fails with ``PermissionError [WinError 32]``.

``tests/e2e`` is not an importable package, so the conftest is loaded by path
under a unique module name and the backstop is exercised against a real
short-lived child process.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

CONFTEST_PATH = Path(__file__).resolve().parents[1] / "e2e" / "conftest.py"


@pytest.fixture
def e2e_conftest() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e_conftest_under_test", CONFTEST_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reap_terminates_and_deregisters_tracked_process(e2e_conftest: ModuleType) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    e2e_conftest._LOCAL_API_PROCESSES.add(proc)
    try:
        assert proc.poll() is None  # still running before reap
        e2e_conftest._reap_local_api_processes()
        assert proc.poll() is not None  # terminated by the backstop
        assert proc not in e2e_conftest._LOCAL_API_PROCESSES  # and deregistered
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_terminate_process_is_noop_on_finished_process(e2e_conftest: ModuleType) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    # Already exited: must be a no-op and must not raise.
    e2e_conftest._terminate_process(proc)
    assert proc.poll() is not None
