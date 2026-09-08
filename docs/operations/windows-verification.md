# Windows verification memory

The Windows verification host kills any Python process that passes 1 GiB, which
is why `tests/unit` runs as sequential shards instead of one pytest command
(audit F-07). This page owns what that budget is actually spent on. It exists
because the budget was raised against the wrong cause, and the next person to
touch it should start from the measurement rather than from the shard size.

**Audience:** maintainers running or tuning the Windows no-Docker verification suite

**Prerequisites:** a local checkout with the project virtualenv installed; the numbers below were measured on the supported 18-core Windows host on 2026-09-07, except where a line attributes them otherwise, with duckdb 1.5.4, numpy 2.3.5, pandas 3.0.3 and pyarrow 24.0.0

## Where the memory goes

Nearly all of it is one flat, per-process cost, paid the first time anything in
the process imports numpy:

| Measured with `scripts/run_windows_unit_shards.py <file>` | Peak |
| --- | --- |
| `import numpy` | 655.6 MiB |
| `import numpy`, with `OPENBLAS_NUM_THREADS=1` | 109.5 MiB |
| `import numpy, pandas, pyarrow`, with the thread variables pinned | 141.0 MiB |
| `INSERT INTO t VALUES ('r', 't', 200)` on a DuckDB file | 86.0 MiB |
| the same insert as `VALUES (?, ?, ?)` with bound parameters | 703.1 MiB |

Two mechanisms combine:

- **OpenBLAS commits per-core scratch buffers when it loads.** On this host that
  is roughly 30 MiB times 18 cores, and it is charged to the process whether or
  not any array arithmetic ever happens. Pinning the pools to a single thread
  removes it.
- **DuckDB reaches numpy on its own.** Passing parameters to `execute()` makes
  the Python client import pandas and pyarrow — and therefore numpy — to convert
  the bound values. The same statement written with literals never loads them.
  Parameter binding is the correct way to write these queries, so this is a cost
  to bound, not to avoid.

That second point is why the heavy modules looked like a random assortment:
every test that writes to a DuckDB store paid it, and nothing else did. Bisecting
one 797 MiB test in `tests/unit/test_analytics_middleware.py` reached
`ensure_analytics_table` at 91.6 MiB and the single session insert after it at
810.8 MiB, which is the whole finding in one line.

## Why a smaller `--shard-size` never helped

The cost is per process and flat, so it does not divide. An earlier pass on the
same host (2026-08-21) recorded a 14-file shard at 830 MiB next to a 147-test
shard at 94 MiB; splitting either one changes nothing, because each resulting
process still imports numpy once. Those numbers were read as "individual heavy
test modules" and the budget was raised instead, which is how the suite arrived
at a 969.8 MiB worst shard against a 1024 MiB guard — 5.3% of headroom.

## What the runner does now

`scripts/run_windows_unit_shards.py` forces `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1` into every child process it starts, for collection as well
as for each shard. The variables are forced rather than defaulted: an
`OMP_NUM_THREADS=8` left over in an operator's shell would otherwise put the
whole cost back without any visible sign.

Neither `src/` nor the unit suite computes with numpy — it is loaded only as
DuckDB's conversion helper — so single-threaded BLAS has nothing to slow down.
Per-module peaks with the pinning in place:

| Module | Before | After |
| --- | --- | --- |
| `tests/unit/test_analytics_middleware.py` | 805.6 MiB | 192.1 MiB |
| `tests/unit/test_versioning.py` | 826.7 MiB | 312.3 MiB |
| `tests/unit/test_usage_db_connection_reuse.py` | 696.0 MiB | 150.6 MiB |

`tests/unit/test_windows_shard_thread_pinning.py` holds the pinning in place and
fails if a change drops it.

Across the whole suite — 3790 tests in 14 shards — the peaks now run 120.7 to
400.4 MiB, against 733 to 969.8 MiB before. The budget is back to being a
ratchet: `DEFAULT_MEMORY_BUDGET_MIB` is 600 MiB, half again the worst shard and
well under the 1024 MiB guard, so a regression trips the runner rather than the
host.

## The API image does not pay this

The cost is an artefact of the development environment, not of the product. No
file under `src/` imports numpy or pandas — the only match there is the Flink
jobs' requirements lock, a separate runtime — no test imports them either, and
`requirements-docker.lock`, which `Dockerfile.api` installs with
`--require-hashes`, contains neither. DuckDB only reaches for them when they
are already installed, which in this repository means a developer checkout.

Re-running the same `INSERT OR REPLACE ... VALUES (?, ?, ?)` with numpy and
pandas made unimportable, which is the shape of the API image, gives the answer
directly: the row is written and the process peaks at 87.6 MiB, the same as the
literal insert. So there is nothing to pin in the container, and nothing to
carry over from the numbers above when sizing the API.

`tests/unit/test_windows_shard_thread_pinning.py` fails if numpy or pandas
enters that lock, because the paragraph above would then need re-measuring
rather than re-reading.

## Re-measuring

To attribute a shard that exceeds its budget, measure its files one at a time —
the runner prints a peak for whatever target it is given:

```bash
python scripts/run_windows_unit_shards.py tests/unit/test_versioning.py
```

Compare a suspect line's cost by isolating it the same way, down to a single
node ID. When a peak moves, check whether the process gained an import before
concluding that a test got heavier.
