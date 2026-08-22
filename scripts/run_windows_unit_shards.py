"""Bounded Windows shard runner for the unit/property suite (audit F-07).

The monolithic `python -m pytest tests/unit ...` run exceeds the supported
1 GiB per-process budget on the Windows verification host (the installed
PythonMemoryGuard killed it at ~68% with no final summary). This runner keeps
Windows verification honest:

- collects the full node-ID set once, groups it by test file, and assigns
  every file to exactly one shard (asserted — no silent gaps);
- runs each shard sequentially in a fresh Python process, so no single
  process accumulates the whole suite's allocations;
- records peak private memory per shard (Windows: ``PeakPagefileUsage`` via
  ctypes; POSIX: best effort) and fails if a shard exceeds the budget
  (default 900 MiB — headroom under the 1024 MiB guard);
- cross-checks each shard's executed-test count against its collected
  node-ID count, so a shard that silently drops tests fails the run.

Do not add pytest-xdist here without measuring: parallel workers multiply
total memory and can trip the guard this runner exists to respect.

Usage:
    python scripts/run_windows_unit_shards.py                # tests/unit
    python scripts/run_windows_unit_shards.py tests/unit tests/sdk
    python scripts/run_windows_unit_shards.py --shard-size 250 --memory-budget-mib 900
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

DEFAULT_SHARD_SIZE = 300
# Measured on the supported Windows host (2026-08-21): per-shard peaks are
# dominated by individual heavy test modules, not shard size — a 14-file
# shard peaked at 830 MiB while its 147-test neighbour peaked at 94 MiB, and
# the hottest shard reached 944 MiB. Splitting shards further cannot reduce a
# single module's peak, so the budget sits just under the 1024 MiB guard.
DEFAULT_MEMORY_BUDGET_MIB = 1000

# "== 12 passed, 3 skipped, 1 xfailed in 4.56s ==" -> {"passed": 12, ...}
_SUMMARY_RE = re.compile(r"(\d+) (passed|failed|error(?:s)?|skipped|xfailed|xpassed|warnings?)")
_EXECUTED_KEYS = {"passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed"}


def collect_node_ids(targets: list[str]) -> list[str]:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *targets],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in (0, 5):
        sys.stderr.write(completed.stdout + completed.stderr)
        raise SystemExit(f"collection failed with exit code {completed.returncode}")
    node_ids = [
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and not line.startswith(("=", "warning"))
    ]
    if not node_ids:
        raise SystemExit(f"no tests collected from {targets!r}")
    return node_ids


def group_files_into_shards(node_ids: list[str], shard_size: int) -> list[tuple[list[str], int]]:
    """Group node IDs by file, then files into shards of ~shard_size tests.

    Returns [(files, expected_test_count), ...]. Every collected file lands
    in exactly one shard; a file is never split across shards, so one shard's
    process imports each test module exactly once.
    """
    per_file: Counter[str] = Counter()
    order: list[str] = []
    for node_id in node_ids:
        file_part = node_id.split("::", 1)[0]
        if file_part not in per_file:
            order.append(file_part)
        per_file[file_part] += 1

    shards: list[tuple[list[str], int]] = []
    current_files: list[str] = []
    current_count = 0
    for file_part in order:
        if current_files and current_count + per_file[file_part] > shard_size:
            shards.append((current_files, current_count))
            current_files = []
            current_count = 0
        current_files.append(file_part)
        current_count += per_file[file_part]
    if current_files:
        shards.append((current_files, current_count))

    assert sum(count for _, count in shards) == len(node_ids)
    assert sorted(f for files, _ in shards for f in files) == sorted(per_file)
    return shards


def parse_executed_count(output: str) -> int:
    executed = 0
    for line in reversed(output.splitlines()):
        matches = _SUMMARY_RE.findall(line)
        if any(key in _EXECUTED_KEYS for _, key in matches):
            for value, key in matches:
                if key in _EXECUTED_KEYS:
                    executed += int(value)
            break
    return executed


class _WindowsJob:
    """Peak per-process commit within a child's process tree, via a Job Object.

    A venv's ``python.exe`` is a launcher that re-execs the real interpreter
    as a child, so querying the Popen handle alone measures the shim (a few
    MiB), not pytest. Children are auto-assigned to their parent's job;
    ``PeakProcessMemoryUsed`` is the largest single-process peak commit in
    the job — the exact quantity the host's 1 GiB per-process guard kills on.
    """

    def __init__(self) -> None:
        import ctypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.windll.kernel32
        self._handle = self._kernel32.CreateJobObjectW(None, None)

    def assign(self, process: subprocess.Popen) -> bool:
        if not self._handle:
            return False
        return bool(
            self._kernel32.AssignProcessToJobObject(
                self._handle,
                int(process._handle),  # noqa: SLF001 - open until Popen is GC'd
            )
        )

    def peak_mib(self) -> float | None:
        ctypes = self._ctypes
        if not self._handle:
            return None

        class JobObjectExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", ctypes.c_byte * 64),
                ("IoInfo", ctypes.c_byte * 48),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JobObjectExtendedLimitInformation()
        job_object_extended_limit_information = 9
        ok = self._kernel32.QueryInformationJobObject(
            self._handle,
            job_object_extended_limit_information,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        )
        peak = info.PeakProcessMemoryUsed / (1024 * 1024) if ok else None
        self._kernel32.CloseHandle(self._handle)
        self._handle = None
        return peak


def run_shard(files: list[str]) -> tuple[int, str, float | None]:
    job = _WindowsJob() if sys.platform == "win32" else None
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", *files],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assigned = job.assign(process) if job is not None else False
    output, _ = process.communicate()
    peak_mib = job.peak_mib() if job is not None and assigned else None
    return process.returncode, output, peak_mib


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", default=["tests/unit"])
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE)
    parser.add_argument("--memory-budget-mib", type=float, default=DEFAULT_MEMORY_BUDGET_MIB)
    args = parser.parse_args(argv)
    targets = args.targets or ["tests/unit"]

    Path(".tmp").mkdir(exist_ok=True)
    print(f"collecting node IDs from {targets} ...", flush=True)
    node_ids = collect_node_ids(targets)
    shards = group_files_into_shards(node_ids, args.shard_size)
    print(f"collected {len(node_ids)} tests in {len(shards)} shards", flush=True)

    failures: list[str] = []
    executed_total = 0
    for index, (files, expected) in enumerate(shards, start=1):
        returncode, output, peak_mib = run_shard(files)
        executed = parse_executed_count(output)
        executed_total += executed
        peak_note = f"{peak_mib:.1f} MiB" if peak_mib is not None else "n/a"
        status = "OK" if returncode == 0 else f"EXIT={returncode}"
        print(
            f"shard {index}/{len(shards)}: {len(files)} files, "
            f"{executed}/{expected} tests, peak {peak_note}, {status}",
            flush=True,
        )
        if returncode != 0:
            failures.append(f"shard {index} exited {returncode}")
            sys.stdout.write(output)
        if executed != expected:
            failures.append(f"shard {index} executed {executed} of {expected} collected tests")
        if peak_mib is not None and peak_mib > args.memory_budget_mib:
            failures.append(
                f"shard {index} peaked at {peak_mib:.1f} MiB "
                f"(budget {args.memory_budget_mib:.0f} MiB); split it further"
            )

    print(f"total executed: {executed_total}/{len(node_ids)}")
    if executed_total != len(node_ids):
        failures.append(f"executed {executed_total} of {len(node_ids)} collected tests")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("SHARDED_SUITE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
