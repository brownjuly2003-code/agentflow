# Immutable evidence index

Audit F-11 (2026-08-21): the checkout root accumulated immutable operational
evidence next to the entry documents, which makes the authoritative state
hard to find. This index is the authoritative catalogue of that evidence.

The files below are **immutable records** — do not edit, rerun, or clean the
identities they describe. Legacy records stay at their recorded root paths
when resume runbooks, `AGENT_STATE.md`, and prior handoffs depend on those
locations. New or deliberately migrated evidence belongs under
`docs/evidence/` (or `docs/perf/`, `docs/operations/` for their existing
series) rather than the documentation root.

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

## Security and dependency records

This table is the audit catalogue for Markdown records stored directly
under `docs/evidence/`. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no
supersession is recorded; a complementary document is not treated as
superseded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [security-s12-2026-07-09.md](security-s12-2026-07-09.md) | 2026-07-09 | offline/unit remainder closed; third-party pen-test **not** claimed | None | None | Does not claim an external penetration test or production acceptance; live schemathesis remains the CI contract, and the live ClickHouse execution matrix remains a separate gate. |
| [security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md) | 2026-07-30 | local/isolated-Mac; core-only API import/HTTP smoke PASS; Trivy 0.70.0 reports 0 HIGH/CRITICAL (ignore-unfixed) after runtime installer removal | None | None | Does not claim pushed/required CI state, published-image signing, external penetration testing, or production acceptance; the next pushed SHA must still pass GitHub Security Scan. |
| [dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md) | 2026-07-30 | local/isolated-Mac; Windows Python 3.13 unit/property 2170 PASS; mcp==1.29.0, pyiceberg==0.11.1, pyiceberg-core==0.7.0 and 39 focused tests PASS | None | None | Does not claim pushed/required CI state, published-image signing, external penetration testing, production acceptance, or remaining live gates (lake-to-serving, restore/replay, soak/rollback). |

## Golden topology acceptance records

This table is the audit catalogue for four golden-topology acceptance
records. The four records are complementary, not a supersession chain.
Columns are identity, ISO date, result, supersedes, superseded by, and
claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [golden-flink-submission-2026-07-30.md](../perf/golden-flink-submission-2026-07-30.md) | 2026-07-30 | PASS only for clean-checkout OCI build plus real Flink job submission/RUNNING observation at exact commit ca82be5a84a58ae37dd71ef80e785deb8e70dcad | None | None | Does not claim full lake-to-serving production E2E, restore/replay, fresh 4h soak plus rollback after traffic, external penetration test, or production acceptance; production.status remains candidate. |
| [golden-operator-acceptance-2026-07-30.md](../perf/golden-operator-acceptance-2026-07-30.md) | 2026-07-30 | PASS only for clean kind + Flink Kubernetes Operator + Helm deployment and recorded stability hold at exact commit 36ed1ecc250ac6c82ccc6f27de1b76a301b17a41 | None | None | Does not claim full lake-to-serving production E2E, restore/replay, fresh 4h soak plus rollback after traffic, external penetration test, or production acceptance; production.status remains candidate. |
| [live-iceberg-materialization-2026-08-01.md](../perf/live-iceberg-materialization-2026-08-01.md) | 2026-08-01 | PASS only for direct events.validated injection through the ed03fc47 lake materializer into live Iceberg, with exact identity match_count=1, on an Operator/Flink stand based on 36ed1ec | None | None | Does not claim Kafka source, ClickHouse/API, restore/replay, fresh soak or rollback, external penetration test, npm approval, Operator acceptance of ed03fc47, or production acceptance; production.status remains candidate. |
| [full-lake-to-serving-e2e-2026-08-01.md](../perf/full-lake-to-serving-e2e-2026-08-01.md) | 2026-08-01 | PASS only for one mixed-SHA event across orders.raw -> accepted 36ed1ec PyFlink -> events.validated -> Iceberg and bridge -> ClickHouse -> task API, using ed03fc47 runtime | None | None | Does not claim same-SHA Operator acceptance, multi-tenant acceptance, restore/replay, fresh soak or rollback, external penetration test, npm approval, or production acceptance; production.status remains candidate. |

## Checkpoint and readiness acceptance records

This table is the audit catalogue for the current checkpoint restore/replay
PASS and the complementary readiness-baselined checkpoint hold. The
checkpoint PASS supersedes the dated 2026-08-01 capacity blocker only for
the restore/replay gate. The readiness hold is a separate complementary,
read-only/no-traffic observation and does not supersede either checkpoint
record or the earlier traffic canary. Columns are identity, ISO date,
result, supersedes, superseded by, and claim boundary. `None` means no
supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [checkpoint-restore-replay-2026-08-02.md](../perf/checkpoint-restore-replay-2026-08-02.md) | 2026-08-02 | PASS only for the isolated checkpoint/savepoint restore/replay gate on runtime SHA ed03fc47: byte-identical E1 replay plus E2, exactly one of each identity across the measured Kafka validated, Iceberg, ClickHouse and API surfaces, DLQ zero, source lag zero, and hard TTL PASS at 565 s | [checkpoint-restore-replay-capacity-blocker-2026-08-01.md](../perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md) | None | Does not claim a four-hour soak, Helm rollback, same-SHA acceptance of later chart/checkpoint configuration, external penetration testing, GitHub Environment/npm approval, or production acceptance; production.status remains candidate. |
| [ready-baselined-checkpoint-hold-2026-08-03.md](../perf/ready-baselined-checkpoint-hold-2026-08-03.md) | 2026-08-03 | RUNTIME_HOLD_PASS only for a 930 s readiness-baselined, read-only, no-traffic hold of an already-running job: completed checkpoints 7675 to 8614, failed checkpoints 1 to 1, with the admitted startup failure attributed to NOT_ALL_REQUIRED_TASKS_RUNNING | None | None | Does not prove canary2, a four-hour soak, rollback, external penetration testing, or production acceptance; the earlier canary remains the latest traffic attempt and production.status remains candidate. |

## F-10 rollback and soak-capacity records (2026-08-23)

These two records stay at the repository root because `docs/STATUS.md`,
`docs/PROJECT_CLOSURE.md`, and `config/project_claims.toml` cite those exact
paths — the same root-path stability as the CI-soak series above. They are
not new evidence under `docs/evidence/`.

This table is the audit catalogue for the corrected rollback mechanics PASS
and the complementary full-soak-plus-rollback-after-traffic capacity
decision. The two records are complementary, not a supersession chain:
rollback mechanics prove a no-traffic Helm pair, while the capacity
decision keeps the full soak gate blocked without a runtime attempt.
Columns are identity, ISO date, result, supersedes, superseded by, and
claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [corrected-rollback-pair-runtime-20260823-01.md](../../corrected-rollback-pair-runtime-20260823-01.md) | 2026-08-23 | PASS only for corrected rollback mechanics (rev5 probe → rev6 = byte-identical rev3; no traffic) | None | None | Does not close the full-soak gate. Does not claim a successful fresh four-hour soak plus rollback after traffic, production acceptance, deploy, or publication; production.status remains candidate. |
| [ci-soak-f02-capacity-decision-20260823-01.md](../../ci-soak-f02-capacity-decision-20260823-01.md) | 2026-08-23 | BLOCKED_HOST_CAPACITY for the golden full-soak plus rollback-after-traffic gate (audit F-02); no r17+ attempt authorized or executed | None | None | Does not claim a runtime soak attempt or a successful fresh four-hour soak plus rollback after traffic, production acceptance, deploy, or publication; the F-02 gate remains open and production.status remains candidate. |
