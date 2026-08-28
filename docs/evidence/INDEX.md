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

## Historical capacity-blocker records

This table is the audit catalogue for the two dated 2026-08-01 capacity
blockers that precede later runtime outcomes. The checkpoint blocker is
superseded by the later checkpoint PASS only for the restore/replay gate. The
soak resource blocker is superseded by the later canary failure only as the
latest attempt state; its dated preflight remains valid. Neither blocker is a
current status owner. Columns are identity, ISO date, result, supersedes,
superseded by, and claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [checkpoint-restore-replay-capacity-blocker-2026-08-01.md](../perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md) | 2026-08-01 | `UNSAFE_CAPACITY` first attempt; capacity change `BLOCKED_BEFORE_MUTATION`; alternate non-protected reclaim `INSUFFICIENT_NON_PROTECTED_RECLAIM`; restore/replay not accepted | None | [checkpoint-restore-replay-2026-08-02.md](../perf/checkpoint-restore-replay-2026-08-02.md) | Historical capacity record only. Does not claim restore/replay acceptance, E1/E2 production or exactness, TTL, four-hour soak, rollback, or production acceptance. The later checkpoint PASS supersedes it only for the restore/replay gate; documented protected recovery is health evidence only. `production.status` remains `candidate`. |
| [golden-4h-soak-rollback-resource-blocker-2026-08-01.md](../perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md) | 2026-08-01 | Read-only preflight `BLOCKED_RESOURCE_CAPACITY`; canary, four-hour soak, and Helm rollback were `NOT STARTED` | None | [golden-4h-soak-canary-failure-2026-08-02.md](../perf/golden-4h-soak-canary-failure-2026-08-02.md) | Historical capacity preflight only. Does not claim canary, four-hour soak, rollback, checkpoint restore/replay, or production acceptance. The later canary failure supersedes it only as the latest attempt state; the dated preflight remains valid. Autonomous Flink recovery is health evidence only. `production.status` remains `candidate`. |

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

## Historical canary-failure and soak-start records

This table is the audit catalogue for two historical predecessor records:
the 2026-08-02 fail-closed catch-up-rate canary failure and the 2026-08-07
`-01` `SOAK_RUNNING` start snapshot. These records are historical, not
the current status owners, and they are not a PASS chain. The canary
failure supersedes
[golden-4h-soak-rollback-resource-blocker-2026-08-01.md](../perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md)
only as the latest attempt state; the blocker's dated preflight remains
valid. `Superseded by` is `None` because the later kind-residual PASS is
differently scoped. The soak-start record supersedes nothing. It is
superseded by
[golden-4h-soak-05-failure-2026-08-08.md](../perf/golden-4h-soak-05-failure-2026-08-08.md)
only as the current soak outcome, reciprocal with the existing soak-05
row. Columns are identity, ISO date, result, supersedes, superseded by,
and claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [golden-4h-soak-canary-failure-2026-08-02.md](../perf/golden-4h-soak-canary-failure-2026-08-02.md) | 2026-08-02 | FAIL_CANARY_CATCHUP_RATE_FLOOR for the fail-closed catch-up-rate canary: producer 2,000/2,000 with zero failures but only 88.715123 eps; downstream snapshot 1092/2000 pipeline and 546/2000 orders; no verifier PASS evidence; four-hour soak, observer, and rollback were not started | [golden-4h-soak-rollback-resource-blocker-2026-08-01.md](../perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md) | None | Does not claim four-hour soak evidence, rollback evidence, or production acceptance; this is historical and not a current status owner; production.status remains candidate. Supersedes the 2026-08-01 resource-capacity blocker only as latest attempt state; the blocker's dated preflight remains valid. |
| [golden-4h-soak-start-2026-08-07.md](../perf/golden-4h-soak-start-2026-08-07.md) | 2026-08-07 | SOAK_RUNNING (not PASS) for identity `golden-4h-soak-rv-20260807-01`: start contract 1,440,000 at 100 delivered eps with `dual_mean_90`; session close about 72k delivered, observer/producer running, verifier and rollback not started | None | [golden-4h-soak-05-failure-2026-08-08.md](../perf/golden-4h-soak-05-failure-2026-08-08.md) | Does not claim soak PASS, mean >=90, rollback PASS, or production acceptance; production.status remains candidate. Historical start snapshot, not a current status owner; soak-05 is the current soak outcome. |

## Kind-residual canary and latest soak records

This table is the audit catalogue for the current D+C1-20 kind-residual
canary PASS and the complementary latest soak-05 terminal outcome. The
two records are complementary, not a PASS chain: the canary proves only
the kind-residual contract and is the prerequisite for later soak work.
The soak-05 record is the current terminal soak outcome and is
`SOAK_FAIL`. It supersedes
[golden-4h-soak-start-2026-08-07.md](../perf/golden-4h-soak-start-2026-08-07.md)
only as the current soak outcome; it does not supersede the canary
prerequisite. The kind-residual PASS does not supersede the differently
scoped 2026-08-02 catch-up-rate canary failure. Columns are identity,
ISO date, result, supersedes, superseded by, and claim boundary. `None`
means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md](../perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md) | 2026-08-07 | PASS_KIND_RESIDUAL_20 only for the D+C1-20 kind-residual contract: residual after produce 7.5127 s within 20 s, 2000/2000 exactness with DLQ/lag zero | None | None | Does not claim dual-mean >=90 PASS (`applied_mean_eps=77.9059` is not dual-mean >=90 PASS), four-hour soak PASS, Helm rollback PASS, or production acceptance; production.status remains candidate. |
| [golden-4h-soak-05-failure-2026-08-08.md](../perf/golden-4h-soak-05-failure-2026-08-08.md) | 2026-08-08 | SOAK_FAIL for identity `-05`: producer 1,440,000/1,440,000 with zero producer failures and about 99.99979 eps, but overall emitted result SOAK_FAIL; Flink was terminal FAILED, no dual-mean verifier PASS JSON existed, and corrected rollback was not started; diagnosis UNRESOLVED_FLINK_TERMINAL_FAILURE due to an evidence-retention gap | [golden-4h-soak-start-2026-08-07.md](../perf/golden-4h-soak-start-2026-08-07.md) | None | Does not claim soak PASS, dual-mean PASS, rollback PASS, or production acceptance; the later topology ABORT text is a downstream symptom, not the cause of the Flink failure; production.status remains candidate and the combined gate stays open. |

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
