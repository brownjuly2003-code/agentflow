"""M-C4 / M-C5 authentication microbenchmark artifact writer.

The authentication phase intentionally reproduces the legacy pre-2026-06-05
O(n) bcrypt lookup measured by ``docs/perf/auth-bench-2026-05-26.md``. The
current ``AuthManager.authenticate()`` uses an Argon2id hash plus deterministic
``key_lookup`` for O(1) candidate resolution; this script must not be described
as a current production-path benchmark.

The rate-window phase still mirrors the current list-trim implementation. Both
measurements are host- and time-dependent diagnostics, not production SLA or
acceptance evidence. The command prints its result and writes an ignored
runtime report under ``.artifacts/perf/`` by default.

Run from the project root::

    python scripts/perf/auth_bench.py
"""

from __future__ import annotations

import argparse
import io
import platform
import secrets
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from agentflow_runtime.serving.api.security import hash_api_key, verify_api_key

BCRYPT_ROUNDS_PROD = 12
BCRYPT_ROUNDS_TEST = 4
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = PROJECT_ROOT / ".artifacts" / "perf" / "auth-bench-current.md"
LIFECYCLE_PATH = PROJECT_ROOT / "docs" / "perf" / "auth-bench.md"
HISTORICAL_RECORD_PATH = PROJECT_ROOT / "docs" / "perf" / "auth-bench-2026-05-26.md"
PROTECTED_REPORT_PATHS = (LIFECYCLE_PATH, HISTORICAL_RECORD_PATH)


class _TeeWriter:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        default=str(DEFAULT_REPORT),
        help="Markdown runtime-report path (defaults under .artifacts/perf/).",
    )
    return parser.parse_args()


def resolve_report_path(report_path: str) -> Path:
    candidate = Path(report_path)
    resolved = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    protected_paths = {path.resolve() for path in PROTECTED_REPORT_PATHS}
    if resolved.resolve() in protected_paths:
        raise ValueError(
            "Tracked authentication benchmark documentation cannot be overwritten; "
            "write runtime artifacts under .artifacts/perf/ instead."
        )
    return resolved


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return s[idx]


def _stats(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "mean_ms": statistics.fmean(samples) * 1000,
        "p50_ms": _percentile(samples, 50) * 1000,
        "p95_ms": _percentile(samples, 95) * 1000,
        "p99_ms": _percentile(samples, 99) * 1000,
        "max_ms": max(samples) * 1000,
    }


def _print_row(label: str, st: dict[str, Any]) -> None:
    print(
        f"  {label:30s}  n={st['n']:>5}  "
        f"mean={st['mean_ms']:>8.3f}ms  p50={st['p50_ms']:>8.3f}ms  "
        f"p95={st['p95_ms']:>8.3f}ms  p99={st['p99_ms']:>8.3f}ms  "
        f"max={st['max_ms']:>8.3f}ms"
    )


def _bench_authenticate_o_n_lookup(rounds: int, n_keys: int, trials: int) -> None:
    """Reproduce the legacy authenticate worst case = miss-then-hit-last-slot.

    This mirrors the pre-2026-06-05 iteration order retained in the historical
    evidence, not the current O(1) ``key_lookup`` candidate path. We measure:

    * **hit-first** — the matching hash is at index 0
    * **hit-last** — the matching hash is at index N-1 (worst case)

    Both scenarios issue a single ``verify_api_key`` per non-matching legacy
    hash plus one final matching call. The scheme is explicit so a future
    default-hash change cannot silently alter the benchmark.
    """
    print(f"\n== legacy authenticate() O(n) lookup (bcrypt rounds={rounds}) ==")
    plaintexts = [secrets.token_urlsafe(24) for _ in range(n_keys)]
    setup_start = time.perf_counter()
    hashes = [hash_api_key(pt, rounds=rounds, scheme="bcrypt") for pt in plaintexts]
    print(
        f"  hashing-setup-done  n_keys={n_keys} "
        f"(took {time.perf_counter() - setup_start:.1f}s wall)"
    )

    hit_first_samples: list[float] = []
    target_first = plaintexts[0]
    for _ in range(trials):
        start = time.perf_counter()
        for h in hashes:
            if verify_api_key(target_first, h):
                break
        hit_first_samples.append(time.perf_counter() - start)

    hit_last_samples: list[float] = []
    target_last = plaintexts[-1]
    for _ in range(trials):
        start = time.perf_counter()
        for h in hashes:
            if verify_api_key(target_last, h):
                break
        hit_last_samples.append(time.perf_counter() - start)

    miss_samples: list[float] = []
    bogus_target = secrets.token_urlsafe(24)
    for _ in range(trials):
        start = time.perf_counter()
        found = False
        for h in hashes:
            if verify_api_key(bogus_target, h):
                found = True
                break
        assert not found
        miss_samples.append(time.perf_counter() - start)

    _print_row(f"hit-first  N={n_keys}", _stats(hit_first_samples))
    _print_row(f"hit-last   N={n_keys}", _stats(hit_last_samples))
    _print_row(f"miss-all   N={n_keys}", _stats(miss_samples))


def _bench_rate_window_trim(window_size: int, calls: int) -> None:
    """Rate-window trim cost.

    Mirrors `AuthManager.is_rate_limited` (line 305):
        window = [stamp for stamp in self._rate_windows[key_id] if stamp > cutoff]
        self._rate_windows[key_id] = window

    We do `calls` invocations against a pre-filled window of `window_size`
    stamps. After each call, we restore the window so subsequent calls
    measure the same workload.
    """
    print(f"\n== is_rate_limited() trim cost (window stamps={window_size}) ==")
    rate_windows: dict[str, list[float]] = defaultdict(list)
    key_id = "tenant:demo"
    now = time.perf_counter()
    rate_windows[key_id] = [now - i * 0.1 for i in range(window_size)]
    snapshot = list(rate_windows[key_id])
    cutoff = now - 60.0

    samples: list[float] = []
    for _ in range(calls):
        rate_windows[key_id] = list(snapshot)
        start = time.perf_counter()
        window = [stamp for stamp in rate_windows[key_id] if stamp > cutoff]
        rate_windows[key_id] = window
        samples.append(time.perf_counter() - start)

    _print_row(f"trim W={window_size}", _stats(samples))


def _verdict(
    label: str,
    samples_p95_ms: float,
    slo_p99_ms: float,
    explain: Callable[[bool], str],
) -> None:
    breaches_slo = samples_p95_ms > slo_p99_ms
    state = "BREACHES" if breaches_slo else "OK"
    print(f"\n>> verdict {label}: {state} ({samples_p95_ms:.2f}ms vs SLO {slo_p99_ms}ms)")
    print(f"   {explain(breaches_slo)}")


def run_benchmark() -> None:
    print("=" * 80)
    print("auth_bench.py — legacy bcrypt M-C4 reproduction / current M-C5 trim")
    print("=" * 80)

    print("\n# Phase 1: legacy bcrypt-12 cost factor — small N")
    print("# (bcrypt-12 setup for N=20 takes ~10s, so we cap N here)")
    _bench_authenticate_o_n_lookup(rounds=BCRYPT_ROUNDS_PROD, n_keys=5, trials=3)
    _bench_authenticate_o_n_lookup(rounds=BCRYPT_ROUNDS_PROD, n_keys=20, trials=3)

    print("\n# Phase 2: bcrypt-4 (CHEAP test factor) — to see asymptote on larger N")
    _bench_authenticate_o_n_lookup(rounds=BCRYPT_ROUNDS_TEST, n_keys=100, trials=10)

    print("\n# Phase 3: rate-window trim across realistic + extreme W")
    _bench_rate_window_trim(window_size=10, calls=5000)
    _bench_rate_window_trim(window_size=120, calls=5000)
    _bench_rate_window_trim(window_size=1000, calls=5000)
    _bench_rate_window_trim(window_size=10000, calls=2000)

    print("\n" + "=" * 80)
    print("Interpret the numbers within their benchmark boundary:")
    print("  M-C4 reproduces the legacy bcrypt O(n) path that motivated the")
    print("       shipped Argon2id + key_lookup O(1) replacement.")
    print("  M-C5 ring-buffer rewrite is justified if trim p95 at W=120 (default")
    print("       rate_limit_rpm) exceeds ~100us in steady-state.")
    print("=" * 80)


def build_runtime_report(captured_output: str) -> str:
    generated = datetime.now(UTC).isoformat()
    return (
        "# Auth benchmark runtime artifact\n\n"
        f"> Generated `{generated}` on `{platform.platform()}` with Python "
        f"`{platform.python_version()}`.\n\n"
        "This host- and time-dependent diagnostic reproduces the explicit legacy bcrypt "
        "O(n) lookup and the current rate-window list trim. It is not a production SLA, "
        "a served-API load test, or production acceptance.\n\n"
        "## Captured output\n\n"
        "```text\n"
        f"{captured_output.rstrip()}\n"
        "```\n"
    )


def main() -> int:
    args = parse_args()
    try:
        report_path = resolve_report_path(args.report)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    captured = io.StringIO()
    with redirect_stdout(_TeeWriter(sys.stdout, captured)):
        run_benchmark()
    captured_output = captured.getvalue()

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_runtime_report(captured_output),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
