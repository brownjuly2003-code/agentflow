"""Audit FB-17: the shard runner must pin BLAS threads in every child process.

Unpinned, OpenBLAS commits one set of scratch buffers per core at import
(measured: 655.6 MiB for `import numpy` on an 18-core host, 109.5 MiB with
OPENBLAS_NUM_THREADS=1). That flat cost is what pushed shards to within 5% of
the host's 1 GiB per-process guard, so losing the pinning would quietly undo
the headroom rather than fail loudly.
"""

import re
import subprocess
from pathlib import Path

import pytest

from scripts import run_windows_unit_shards as runner

ROOT = Path(__file__).resolve().parents[2]


def test_shard_env_pins_both_thread_pools_to_one():
    assert runner.SHARD_ENV == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}


def test_shard_environment_overrides_an_inherited_thread_count(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "18")

    environment = runner.shard_environment()

    assert environment["OMP_NUM_THREADS"] == "1"
    assert environment["OPENBLAS_NUM_THREADS"] == "1"


def test_shard_environment_keeps_the_rest_of_the_parent_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AGENTFLOW_MARKER", "kept")

    assert runner.shard_environment()["AGENTFLOW_MARKER"] == "kept"


def test_run_shard_passes_the_pinned_environment_to_pytest(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class _FakeProcess:
        returncode = 0

        def communicate(self):
            return "1 passed in 0.01s", ""

    class _NoJob:
        """Stand in for the Job Object: a fake Popen has no handle to assign."""

        def assign(self, process):
            return False

    def _fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return _FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(runner, "_WindowsJob", _NoJob)

    returncode, output, _ = runner.run_shard(["tests/unit/test_example.py"])

    assert returncode == 0
    assert "passed" in output
    assert captured["env"] is not None, "run_shard inherited the environment instead of pinning it"
    for name, value in runner.SHARD_ENV.items():
        assert captured["env"][name] == value


def test_collect_node_ids_pins_the_environment_too(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "tests/unit/test_example.py::test_one\n", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    runner.collect_node_ids(["tests/unit"])

    assert captured["env"] is not None
    for name, value in runner.SHARD_ENV.items():
        assert captured["env"][name] == value


def test_docstring_quotes_no_budget_that_disagrees_with_the_constant():
    """A stale "default 900 MiB" in the docstring outlived two budget changes."""
    quoted = {int(match) for match in re.findall(r"(\d+) MiB", runner.__doc__ or "")}

    assert quoted <= {1024, int(runner.DEFAULT_MEMORY_BUDGET_MIB)}, (
        f"docstring quotes {sorted(quoted)} MiB; the budget is "
        f"{runner.DEFAULT_MEMORY_BUDGET_MIB:.0f} MiB and 1024 is the host guard"
    )


def test_the_api_image_still_ships_neither_numpy_nor_pandas():
    """The runbook's "the API image does not pay this" rests on this lock.

    DuckDB imports pandas (and so numpy, and so OpenBLAS) only when they are
    installed, so the measured 87.6 MiB for a parameterized insert in the image
    holds exactly as long as this stays true.
    """
    lock = (ROOT / "requirements-docker.lock").read_text(encoding="utf-8")
    requirements = {
        line.split("==", 1)[0].strip().lower()
        for line in lock.splitlines()
        if "==" in line and not line.lstrip().startswith(("#", "--"))
    }

    intruders = requirements & {"numpy", "pandas"}
    assert not intruders, (
        f"{sorted(intruders)} entered requirements-docker.lock; re-measure before "
        "trusting docs/operations/windows-verification.md on the API image"
    )


def test_budget_failure_hint_does_not_advise_splitting_shards():
    hint = runner.BUDGET_FAILURE_HINT

    assert "split it further" not in hint
    assert "run_windows_unit_shards.py <file>" in hint
    assert "SHARD_ENV" in hint
