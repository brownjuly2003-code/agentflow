# The `Load Test` was not bimodal because of the runner

**Date:** 2026-07-09 · **Status:** root cause found and fixed · **Supersedes:** the
"CI runner speed" reading of finding N1 in `plan_07_07_26.md`.

## What we thought

`Load Test` runs split into two clusters — roughly 44 rps at p99 ~150 ms, or
roughly 29 rps at p99 ~1500 ms against thresholds of 900–1200 ms. Runs of both
kinds existed before and after the B1 usage-write fix, so the split was read as
runner speed and filed as "not code". The proposed remedies were all variations
on making the gate tolerate it: re-run on red, take the best of two runs, or
normalise the threshold against measured rps.

## Why that reading does not survive arithmetic

Across the red/green runs, rps varies by 1.5× while p99 varies by 10×. A
machine that is 1.5× slower does not produce a 10× tail; it produces a 1.5×
tail. The nonlinearity means something in the system amplifies a small change
in service time, which is the signature of a queue, not of a slow CPU.

The decisive clue is in the spread. If the red branch were "an unlucky runner",
red runs would scatter. They do not:

| branch | runs | aggregate rps |
|--------|------|---------------|
| red    | 3    | 29.4 · 29.1 · 28.9 — spread 1.7% |
| green  | 9    | 37.0 … 46.2 — spread 25% |

Three independent red runs land within 1.7% of each other. That is an
attractor, not bad luck.

## The mechanism

Every authenticated request wrote its own `api_usage` row before the response
was produced (`AuthMiddleware` → `run_in_threadpool(record_usage)` →
`EmbeddedControlPlaneStore.record_api_usage`). DuckDB serializes writers and
commits per row, so each request queued behind one fsync.

The load client is closed-loop: 15 users, `wait_time = between(0.1, 0.5)`. Let
`s` be the usage-write service time.

- **Unsaturated branch.** The writer keeps up, so rps is bounded by think time:
  `15 / (0.3 + L) ≈ 48.9` at small `L`. Observed green maximum: 46.2 rps.
- **Saturated branch.** Requests queue at the serialized writer, so
  `L ≈ C·s` where the server-side concurrency is `C = rps · L`. Substituting
  gives `rps = 1/s` — **independent of the number of users**. That is why the
  red runs agree with each other: they are all sitting on `1/s`.

At 29 rps the implied `s` is ≈ 34 ms, a plausible fsync on a slow shared disk.
The bifurcation point is `s ≈ 1/48.9 ≈ 20 ms`: below it the run is think-time
bound and fast, above it the run collapses onto `1/s`. The runner's disk merely
decides which side of 20 ms the commit lands on. **The cap is ours.**

## Evidence

**1. The writer serializes (isolated, `duckdb 1.5.1`, one connection, cursors
per call, the shipped retry loop).** p50 grows linearly with concurrency and
throughput saturates — the shape of a single-server queue. The retry/backoff
path was never entered, so it is not the amplifier:

| threads | 1 | 2 | 4 | 8 | 15 | 30 |
|---------|---|---|---|---|----|----|
| p50 (ms) | 2.6 | 4.1 | 9.0 | 18.0 | 34.8 | 62.7 |
| inserts/s | 148 | 244 | 275 | 326 | 325 | 374 |

**2. The collapse reproduces on the shipped code.** Serving the real API with
the CI load profile and `sleep(s)` injected into `record_api_usage`:

| `s` | rps | p50 (ms) | p99 (ms) |
|-----|-----|----------|----------|
| 0 ms | 43.9 | 27 | 100 |
| 10 ms | 37.8 | 76 | 250 |
| 25 ms | 36.6 | 82 | 320 |
| **34 ms** | **31.4** | **160** | 430 |
| 60 ms | 8.3 | 110 | 21000 |

At `s = 34 ms` the harness lands on 31.4 rps / p50 160 ms; CI's red branch is
29.1 rps / p50 161 ms.

**3. Taking the write off the request path removes the sensitivity.** Same
injected `s`, rows enqueued to a background writer:

| `s` | in-path | off-path |
|-----|---------|----------|
| 34 ms | 31.4 rps · p99 430 | 37.9 rps · p99 340 |
| 60 ms | 8.3 rps · p99 21000 · **FAIL** | 37.2 rps · p99 320 · PASS |

Off-path throughput is flat in `s`. In-path throughput is `1/s`.

## The fix

`src/serving/api/auth/usage_writer.py`. The request enqueues a `UsageRow` and
returns; one background thread drains the queue and writes.

Batching is not an optimisation here, it is part of the fix. A per-row
background writer would still commit at `1/s` rows per second — below the
request rate the API can otherwise serve — so the ceiling would simply move
from request latency into a queue that silently overflows. `record_api_usage_batch`
puts one commit under N rows, lifting the accounting ceiling to `N/s`.

## What this costs

Durability moves from "committed before the response" to "committed shortly
after". A crash loses at most the queued rows. `api_usage` backs one admin read
(`GET /v1/admin/usage`) — it is not billing and not rate limiting — and rows
were already droppable when the store exhausted its retries. Reads that must
see their own writes call `flush_usage`; the API lifespan closes the writer on
shutdown. A full queue sheds rows into `agentflow_usage_rows_dropped_total`
rather than stalling the request it was counting.

## What this does not claim

The CI disk is still variable, and a heavily degraded runner can still miss a
p99 threshold. What is gone is the *amplifier*: a 1.5× slower commit now costs
a 1.5× slower commit, not a collapse of the whole API onto `1/s`. Finding N1
therefore needs no threshold normalisation — the gate was reporting a real
defect, and the honest response was to fix it rather than widen the gate.

## Beyond CI

This was never only a CI property. Any deployment on the embedded control plane
served at most `1 / commit_latency` authenticated requests per second, and every
request paid the queueing delay. The Load Test was the only place it was visible.
