"""M-C4 / M-C5 perf-baseline microbench for AuthManager hot path.

Decides whether the deferred audit findings warrant a rewrite:

* **M-C4** — `AuthManager.authenticate()` iterates `_hashed_keys` calling
  `verify_api_key()` (bcrypt) on each. Worst case is N × bcrypt-verify.
* **M-C5** — `AuthManager.is_rate_limited()` rebuilds the per-key window
  with a list comprehension on every call. Cost is O(W) where W is the
  number of in-window stamps.

Runs both at realistic production scale and prints a verdict table.

Run::

    python scripts/perf/auth_bench.py
"""

from __future__ import annotations

import secrets
import statistics
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from src.serving.api.security import hash_api_key, verify_api_key

BCRYPT_ROUNDS_PROD = 12
BCRYPT_ROUNDS_TEST = 4


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
    """Authenticate worst case = miss-then-hit-last-slot.

    Mirrors the actual production iteration order in
    `AuthManager.authenticate` (line 279). We measure two scenarios:

    * **hit-first** — the matching hash is at index 0
    * **hit-last** — the matching hash is at index N-1 (worst case)

    Both scenarios issue a single `verify_api_key` per non-matching hash
    plus one final matching call. Bcrypt-12 is the production cost.
    """
    print(f"\n== authenticate() O(n) hashed-key lookup (bcrypt rounds={rounds}) ==")
    plaintexts = [secrets.token_urlsafe(24) for _ in range(n_keys)]
    setup_start = time.perf_counter()
    hashes = [hash_api_key(pt, rounds=rounds) for pt in plaintexts]
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


def main() -> None:
    print("=" * 80)
    print("auth_bench.py — M-C4 / M-C5 perf-baseline microbench")
    print("=" * 80)

    print("\n# Phase 1: bcrypt-12 (PRODUCTION cost factor) — small N")
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
    print("Use the numbers above to decide:")
    print("  M-C4 rewrite (lookup-by-hash-prefix) is justified if hit-last p95")
    print("       at bcrypt-12 / N=20 exceeds load-test gate (1100ms POST p99).")
    print("  M-C5 ring-buffer rewrite is justified if trim p95 at W=120 (default")
    print("       rate_limit_rpm) exceeds ~100us in steady-state.")
    print("=" * 80)


if __name__ == "__main__":
    main()
