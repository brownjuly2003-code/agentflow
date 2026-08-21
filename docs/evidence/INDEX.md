# Immutable evidence index

Audit F-11 (2026-08-21): the checkout root accumulated immutable operational
evidence next to the entry documents, which makes the authoritative state
hard to find. This index is the authoritative catalogue of that evidence.

The files below are **immutable records** — do not edit, rerun, or clean the
identities they describe. They stay at their recorded root paths because the
resume runbooks, `AGENT_STATE.md`, and prior handoffs link to those exact
paths; new evidence documents belong under `docs/evidence/` (or `docs/perf/`,
`docs/operations/` for their existing series) rather than the root.

Entry documents (start here, not below): `README.md`, `docs/STATUS.md`,
`docs/SESSION_HANDOFF.md`, `docs/operations/ci-soak-next-session-runbook.md`.

## CI-soak rehearsal series (r1–r12, consumed)

| Record | What it fixes in time |
| --- | --- |
| [ci-soak-r1-r7-architecture-audit.md](../../ci-soak-r1-r7-architecture-audit.md) | Architecture audit and readiness contract for the r-series |
| [ci-soak-architecture-gate-plan.md](../../ci-soak-architecture-gate-plan.md) | Exact-HEAD architecture gate design |
| [ci-soak-preflight-7e8ec87-r9.md](../../ci-soak-preflight-7e8ec87-r9.md) | r9 preflight record |
| [ci-soak-r9-rehearsal-20260821-01.md](../../ci-soak-r9-rehearsal-20260821-01.md) | Immutable r9 rehearsal FAIL report |
| [ci-soak-r10-orchestration-stop-20260821-01.md](../../ci-soak-r10-orchestration-stop-20260821-01.md) | r10 stop before external mutation |
| [ci-soak-r12-preflight-fail-20260821-01.md](../../ci-soak-r12-preflight-fail-20260821-01.md) | r12 `output_marker_hash_mismatch` preflight failure |
| [ci-soak-runtime-harness.md](../../ci-soak-runtime-harness.md) | Runtime harness history |

Future attempts (r13+) generate their identities with
`scripts/golden_soak/gen_attempt_bundle.py` (audit F-10) and record evidence
under `docs/evidence/`.

## Mac runtime and dependency records

| Record | What it fixes in time |
| --- | --- |
| [api-duckdb-non-target-scratch-checks.md](../../api-duckdb-non-target-scratch-checks.md) | API DuckDB scratch checks on non-target hosts |
| [clickhouse-aggregate-verification-closure.md](../../clickhouse-aggregate-verification-closure.md) | ClickHouse aggregate verification closure |
| [colima-runtime-stabilization.md](../../colima-runtime-stabilization.md) | Colima runtime stabilization on the Mac host |
| [external-dependency-recovery-preparation-20260817.md](../../external-dependency-recovery-preparation-20260817.md) | External dependency recovery preparation |
| [flink-failure-evidence-retention.md](../../flink-failure-evidence-retention.md) | Flink failure evidence retention policy |
| [mac-clickhouse-loopback-rebind-20260821-01.md](../../mac-clickhouse-loopback-rebind-20260821-01.md) | Mac ClickHouse loopback rebind record |
