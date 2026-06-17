# AuthManager perf-baseline (M-C4 / M-C5 audit closure)

> **M-C4 CLOSED 2026-06-05**: the deferred hash-format swap shipped —
> argon2id + deterministic peppered `key_lookup` digest, O(1) candidate
> resolution in `authenticate()`. N=20 hit-last cold went from ≈ 8.1 s
> (table below) to ≈ 34 ms; misses from ≈ 8.2 s to ≈ 0.1 ms. The bcrypt
> numbers below are retained as the historical baseline that motivated the
> swap. See `docs/runbooks/auth-401-spike.md` for the operational guidance.

**Date:** 2026-05-26
**Machine:** Intel Ultra 5 125H, Windows 11, Python 3.13, `Cool Limited` power profile
**Bench script:** [`scripts/perf/auth_bench.py`](../../scripts/perf/auth_bench.py)
**Audit findings closed:** M-C5 (not a bottleneck); M-C4 (mitigated, action item added)

An internal 2026-05-25 audit deferred two
medium-priority findings pending a perf measurement: M-C4 (O(n) hashed
key lookup in `authenticate()`) and M-C5 (O(n) rate-window trim in
`is_rate_limited()`). This document records the measurement and the
resulting decisions.

## Bench setup

- Production bcrypt cost factor: `bcrypt_rounds=12` (from
  [`src/serving/api/security.py:33`](../../src/serving/api/security.py)).
- Cheap test bcrypt factor: `bcrypt_rounds=4` (lets us push N=100
  without the setup phase blowing past 10 s).
- The bench measures the same iteration pattern as
  [`AuthManager.authenticate()`](../../src/serving/api/auth/manager.py#L272)
  for M-C4 and [`is_rate_limited()`](../../src/serving/api/auth/manager.py#L301)
  for M-C5 — no mocks; uses the same `verify_api_key` /
  `hash_api_key` from `security.py`.

## Phase 1: M-C4 — `authenticate()` O(n) lookup at production cost

| Scenario | N (hashed keys) | trials | mean | p95 | max |
|----------|-----------------|--------|------|-----|-----|
| **hit-first** | 5 | 3 | 349.5 ms | 415.4 ms | 415.4 ms |
| **hit-last** (worst case) | 5 | 3 | **1910.7 ms** | **1934.4 ms** | 1934.4 ms |
| **miss-all** (DoS) | 5 | 3 | 1953.9 ms | 1973.5 ms | 1973.5 ms |
| **hit-first** | 20 | 3 | 402.6 ms | 414.5 ms | 414.5 ms |
| **hit-last** (worst case) | 20 | 3 | **7928.0 ms** | **8146.6 ms** | 8146.6 ms |
| **miss-all** (DoS) | 20 | 3 | 8045.5 ms | 8221.9 ms | 8221.9 ms |

Phase 2 with `bcrypt_rounds=4` and N=100 confirms linearity: hit-last
≈ 162 ms (vs hit-first 1.5 ms) — the cost is **dominated by the
per-call bcrypt verify, not by Python iteration overhead**.

### Interpretation

At production cost factor `bcrypt_rounds=12`, **each `verify_api_key`
call costs ≈ 400 ms** on this hardware. Worst-case `authenticate()`
runs N verifies → N × 400 ms.

**The 1100 ms load-test gate
([`tests/load/thresholds.py`](../../tests/load/thresholds.py))
for POST p99 is exceeded at N ≥ 3.** At N=20 (multi-tenant production
scale), worst case is 8 seconds for a single auth.

### Already-deployed mitigations

The hot-path in
[`AuthManager.authenticate()`](../../src/serving/api/auth/manager.py#L272)
already includes two production-grade mitigations that the audit
finding did not credit:

1. **Plaintext cache after first verify** —
   [`manager.py:284-285`](../../src/serving/api/auth/manager.py#L284)
   stashes the verified plaintext in `self.keys_by_value[api_key] =
   matched` and `self._runtime_plaintext_by_hash[item.key_hash] =
   api_key`. The next auth for the same key takes the fast
   `compare_digest` path at
   [`manager.py:273-278`](../../src/serving/api/auth/manager.py#L273) in
   microseconds. **Steady-state per-key cost after first auth is
   O(1).**
2. **Failed-auth backoff** — `_failed_auth_windows` (session-23
   H-C4 closure) blocks repeated failures from the same source so a
   flood of bogus keys can't burn N × 400 ms per request indefinitely.

### Remaining worst-case scenarios

- **Cold-cache first auth per key after process restart / SIGHUP
  reload** — for an active tenant with a hashed key in the last
  position of `_hashed_keys`, the first auth after reload pays the
  full N × bcrypt cost once. Then plaintext cache amortises.
- **DoS: flood of distinct bogus plaintexts** — each forces N bcrypt
  verifies before failure. `_failed_auth_windows` from session 23
  rate-limits this per source so it's bounded.

### Decision

**M-C4 stays partially deferred** with explicit guidance instead of
a rewrite:

- **Production guidance:** keep `_hashed_keys` ≤ 10 per AuthManager
  instance. Above that, latency at process boot or after SIGHUP
  reload becomes user-visible. Documented in
  [`docs/runbooks/auth-401-spike.md`](../runbooks/auth-401-spike.md)
  follow-up (linked below).
- **No code rewrite right now.** bcrypt is self-salted so a true
  prefix index would require swapping the hash format (argon2id with
  a deterministic peppered segment is one path) — a major change
  with security review implications. Out of scope until a real
  multi-tenant deployment hits the cap.
- **Re-evaluate trigger:** any production tenant with > 10 hashed
  keys, or a documented SIGHUP-reload latency complaint.

## Phase 3: M-C5 — `is_rate_limited()` window-trim cost

| W (in-window stamps) | calls | mean | p95 | p99 | max |
|----------------------|-------|------|-----|-----|-----|
| 10 | 5000 | 0.001 ms | 0.001 ms | 0.002 ms | 0.122 ms |
| 120 (default `rate_limit_rpm`) | 5000 | **0.006 ms** | **0.006 ms** | 0.009 ms | 0.203 ms |
| 1000 | 5000 | 0.042 ms | 0.054 ms | 0.098 ms | 1.147 ms |
| 10000 (pathological) | 2000 | 0.325 ms | 0.448 ms | 0.619 ms | 6.265 ms |

### Interpretation

At the production default `rate_limit_rpm=120`, the per-call trim
takes **6 microseconds at p95**. Even at the W=10000 pathological
case (would require >100 distinct keys with full saturation — already
guarded by `_sweep_expired_windows` from session 23), p95 is
0.448 ms — well under any meaningful SLO.

### Decision

**M-C5 closed as not-a-bottleneck.** The audit's worry about "O(n)
window trimming on each request" is true asymptotically but the
constant factor (list comprehension on floats) makes it invisible at
realistic W. A ring-buffer rewrite would save microseconds per call
at the cost of new code surface, harder reasoning under concurrent
load, and an extra invariant to maintain across `_sweep_expired_windows`.
**Not worth the trade.**

## Summary

| Finding | Audit verdict | Bench verdict | Action |
|---------|---------------|---------------|--------|
| **M-C4** O(n) auth lookup | "Bottleneck при масштабировании" | **Real at N ≥ 3 / bcrypt-12**, but plaintext cache (line 284) + failed-auth backoff make steady-state O(1) | Stay deferred + documented guidance (≤ 10 hashed keys); rewrite out of scope |
| **M-C5** O(n) rate-window trim | "CPU bottleneck под нагрузкой" | **Not a bottleneck**: 6 μs p95 at W=120 | **Close.** Ring-buffer rewrite skipped — gains negligible vs added complexity |

## Reproducibility

```bash
cd D:/DE_project
python -m scripts.perf.auth_bench
```

Setup phase takes ~10 s for the bcrypt-12 N=5 row, ~40 s for N=20.
Total runtime ~3 minutes including phase 2 + 3.
