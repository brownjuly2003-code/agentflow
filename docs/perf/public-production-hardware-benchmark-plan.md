# Public Production-Hardware Benchmark Plan

## Status

Done on 2026-06-05 using the GitHub-hosted arm64 runner for public
repositories (`ubuntu-24.04-arm`, Neoverse-N2, 4 vCPU) as the available ARM
server class, with a real benchmark run recorded in
[arm-server-benchmark-2026-06-05.md](arm-server-benchmark-2026-06-05.md)
(run 27012731848, 0 failures, all gates passed). No `c8g.4xlarge` claim is
made; the `c8g.4xlarge+` procedure below remains the preferred path if
production-grade hardware becomes available.

Status as of 2026-05-04: blocked on approved production-hardware access,
budget, and operator-run evidence.

The checked-in single-node baseline remains the only release evidence until an
operator runs the benchmark on approved production-class hardware and records
the artifacts listed below.

Access triage on 2026-05-04 found only historical local benchmark artifacts
under `.artifacts/benchmark/`; no approved `c8g.4xlarge+` or equivalent host,
budget owner, operator-run transcript, production-hardware JSON/report, host
metadata, fixture-safety confirmation, or publication approval was available.
No cloud instance was provisioned and no paid benchmark was run.

Next operator packet to unblock review:

- Benchmark owner, budget approval, instance class, region, OS image, lifecycle
  owner, and commit SHA.
- Fixture-safety confirmation that no production data, customer records, or
  credentials were used.
- Command transcript with exit codes plus JSON results, human-readable report,
  logs, and host metadata.
- Caveats for topology, warmup, noisy-neighbor risk, excluded endpoints, and
  publication approval.

## Target Hardware

Minimum target class: `c8g.4xlarge+` or an equivalent dedicated ARM64 or x86_64
production-class host with:

- 16 or more vCPU.
- 32 GiB or more memory.
- Local network path to the benchmark API host.
- No co-located noisy workload during the measured window.
- OS, kernel, Docker, Python, and package versions captured in the result note.

Use the same instance class for all published comparison runs. Do not compare
production-hardware results against laptop, GitHub-hosted runner, or ad hoc
single-node development numbers.

## Prerequisites

Before a public benchmark run, the following must be in place:

- Provisioned cloud or dedicated benchmark hardware.
- Instance class, region, OS image, and lifecycle owner.
- Benchmark API target and data seed plan.
- Confirmation that no production data, credentials, or customer records are
  used in the benchmark fixture.
- Evidence location for JSON results, human-readable report, run logs, and
  environment metadata.
- Explicit approval to publish summarized latency and throughput numbers.

## Operator Runbook

Run from a clean checkout on the benchmark host after installing the normal
project prerequisites. These commands are examples for the operator-run record;
do not run them from guarded autopilot.

```bash
git rev-parse --short HEAD
python --version
docker version
docker compose version

docker compose up -d redis
python scripts/run_benchmark.py \
  --results-json .artifacts/benchmark/production-hardware-current.json \
  --report-path .artifacts/benchmark/production-hardware-benchmark.md
python scripts/check_performance.py \
  docs/benchmark-baseline.json \
  .artifacts/benchmark/production-hardware-current.json
```

If the operator uses a remote API target, capture the exact target URL,
deployment commit, region, instance class, and whether the client and server run
on the same host, same private network, or separate networks.

## Required Artifacts

Publish only redacted, non-secret artifacts:

- Benchmark host metadata: instance class, CPU architecture, memory, OS, Docker,
  Python, Git commit, date, and region.
- Benchmark command transcript with exit codes.
- JSON results from `scripts/run_benchmark.py`.
- Human-readable benchmark report.
- `scripts/check_performance.py` output.
- Notes on data fixture, API target topology, warmup, and measured duration.
- Any excluded endpoint or known environmental caveat.

Do not publish credentials, private hostnames, account IDs, raw production data,
customer identifiers, or cloud billing details.

## Publication Gate

Public benchmark publication is allowed only after:

- The operator-run artifacts are complete.
- The benchmark uses approved synthetic or non-sensitive fixture data.
- The hardware and topology are described clearly enough to reproduce.
- The result note distinguishes production-hardware evidence from historical
  single-node and CI-runner baselines.
- Release readiness links to the new evidence without replacing historical
  baselines.

Until then, keep release readiness marked as pending for public production
hardware benchmarks.
