# ARM Server Benchmark — 2026-06-05

First real benchmark run on ARM server hardware, closing backlog item 21 under
the 2026-06-05 operator decision that amended the hardware class.

## Hardware Class Decision

The original plan targeted `c8g.4xlarge+` (AWS Graviton4, 16 vCPU), which
requires a cloud budget and payment card that do not exist (the item-18
constraint). The operator accepted the free GitHub-hosted arm64 runner for
public repositories as the $0-budget ARM server class:

- Runner label: `ubuntu-24.04-arm`
- CPU: Arm **Neoverse-N2** (Cobalt 100), Armv9-A, **4 vCPU** — honestly
  recorded as 4 vCPU, not 16; same ARM server architecture generation as
  Graviton.
- RAM: 15.6 GB
- OS: Linux 6.17.0-1015-azure aarch64, Python 3.11.15

`c8g.4xlarge+` remains the preferred class if budget ever appears; the
original plan is preserved in
[public-production-hardware-benchmark-plan.md](public-production-hardware-benchmark-plan.md).

## Run Provenance

- Workflow: `.github/workflows/benchmark-arm.yml` (workflow_dispatch-only)
- Run: <https://github.com/brownjuly2003-code/agentflow/actions/runs/27012731848>
  (conclusion: success)
- Commit: `60e0f3d`
- Generated: `2026-06-05T11:41:33+00:00`
- Canonical harness: `scripts/run_benchmark.py` (50 users, spawn rate 10/s,
  60s, 10s warmup, fresh seeded DuckDB) — identical to the x64 `perf-check`
  gate.
- Raw artifacts (downloaded from the run, byte-identical):
  [arm-benchmark-2026-06-05/](arm-benchmark-2026-06-05/)

## Results

| Endpoint | Requests | Failures | RPS | p50 | p95 | p99 |
|----------|----------|----------|-----|-----|-----|-----|
| ALL | 554 | 0 | 37.41 | 6.0 ms | 44.0 ms | 150.0 ms |
| GET /v1/entity/order/{id} | 84 | 0 | 5.67 | 4.0 ms | 34.0 ms | 130.0 ms |
| GET /v1/entity/product/{id} | 72 | 0 | 4.86 | 4.0 ms | 33.0 ms | 84.0 ms |
| GET /v1/entity/user/{id} | 45 | 0 | 3.04 | 4.0 ms | 32.0 ms | 150.0 ms |
| GET /v1/metrics/{name} | 147 | 0 | 9.93 | 5.0 ms | 35.0 ms | 120.0 ms |
| POST /v1/query | 98 | 0 | 6.62 | 8.0 ms | 100.0 ms | 150.0 ms |
| POST /v1/batch | 108 | 0 | 7.29 | 8.0 ms | 87.0 ms | 150.0 ms |

## Gate Verdict

Release gate for `/v1/entity/*` is p50 < 100 ms and p99 < 500 ms. Every
entity endpoint passes with wide margin (worst entity p50 4.0 ms, worst
entity p99 150.0 ms). Zero failures across 554 requests.

For context, the checked-in 2026-04-17 x64 single-node baseline recorded
entity p50 38-55 ms and p99 290-320 ms; this ARM run is faster on both
percentiles. The numbers are not strictly comparable across hosts and are
recorded side by side, not as a regression claim.

## Scope Honesty

- This is real ARM server hardware, but a 4-vCPU shared CI runner — not a
  dedicated 16-vCPU `c8g.4xlarge`. No claim about `c8g.4xlarge` performance
  is made.
- Fixture safety: the run used the standard synthetic seeded DuckDB fixture
  (`--burst 500`); no production data, customer records, or credentials were
  involved.
- Publication scope: this document and the raw artifacts in the repo are the
  publication; no external benchmark claims are published elsewhere.
