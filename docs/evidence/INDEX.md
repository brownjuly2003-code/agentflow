# Immutable evidence index

Audit F-11 (2026-08-21): the checkout root accumulated immutable operational
evidence next to the entry documents, which makes the authoritative state
hard to find. This index is the authoritative catalogue of that evidence.

The catalogue identity rows below are **immutable records** — do not edit,
rerun, or clean the identities they describe. The classified non-identity
paths below retain their stated lifecycle and are outside this immutability
rule. Legacy records stay at their recorded root paths when resume runbooks,
`AGENT_STATE.md`, and prior handoffs depend on those locations. New or
deliberately migrated evidence belongs under `docs/evidence/` (or `docs/perf/`,
`docs/operations/` for their existing series) rather than the documentation
root.

Entry documents (start here, not below): `README.md`, `docs/STATUS.md`,
`docs/SESSION_HANDOFF.md`, [`docs/perf/README.md`](../perf/README.md), and
`docs/operations/ci-soak-next-session-runbook.md`.

For inventory only, a tracked `docs/perf` Markdown path is represented when
this index links it explicitly, whether as an identity, a classified supporting
companion, or a navigation entry. Representation does not make navigation or
supporting companions evidence identities; identity counts come only from the
catalogue table rows.

## Classified non-identity performance paths

These five paths complete the tracked `docs/perf` Markdown inventory without
manufacturing evidence identities. They are decisions, procedures, generated
output, plans, or implementation companions. Supersession belongs only to the
catalogue identity rows below; none of these paths has a `supersedes` or
`superseded by` relationship.

| Path | Class | Status/claim owner | Evidence relationship |
| --- | --- | --- | --- |
| [benchmark-split-decision.md](../perf/benchmark-split-decision.md) | Dated decision | The executable CI gate is owned by `.github/workflows/perf-regression.yml` and the current benchmark scripts. | Supporting decision, not a current status owner and not an evidence identity. |
| [bridge-ch-native-apply-q1-2026-07-09.md](../perf/bridge-ch-native-apply-q1-2026-07-09.md) | Implementation companion | The Q1.2 measured result is owned by [throughput-realpath-q12-2026-07-09.md](../perf/throughput-realpath-q12-2026-07-09.md). | Code-slice explanation, not an evidence identity. |
| [entity-benchmark-contract.md](../perf/entity-benchmark-contract.md) | Current benchmark reference | Executable behavior is owned by `scripts/profile_entity.py` and `scripts/run_benchmark.py`. | Measurement procedure, not a measured result and not an evidence identity. |
| [load-benchmark-latest.md](../perf/load-benchmark-latest.md) | Generated mutable report | This path is overwritten by its owner, `scripts/run_benchmark.py`. | Latest generated output, not an immutable evidence identity. |
| [public-production-hardware-benchmark-plan.md](../perf/public-production-hardware-benchmark-plan.md) | Operator plan | The completed shared-runner result is owned by [arm-server-benchmark-2026-06-05.md](../perf/arm-server-benchmark-2026-06-05.md); a dedicated production-class result remains absent. | Procedure and access boundary, not an evidence identity. |

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

## Historical entity hot-path optimization records

This table catalogues three human-authored identities from one bounded local
entity hot-path investigation. Their JSON/SVG companions remain supporting
artifacts, not separate evidence identities. The records are chronological
complementary stages, not a document supersession chain. In particular, the
recorded 936 -> 361 -> 962 -> 289 -> 167 ms sequence is not a monotonic
performance trajectory: it combines different windows, profiling overhead,
and noisy before/after series. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [entity-profile-2026-04-24.md](../perf/entity-profile-2026-04-24.md) | 2026-04-24 | Composite historical dossier. Baseline HEAD `97a1902` on Windows 11, Intel i7 with 18 logical cores, 15.5 GB RAM, Python 3.13.7, Redis in Docker, DuckDB, and a localhost API recorded p50/p95/p99 179.29/615.62/936.34 ms, 68.57 RPS, and 2000/2000 successes. A later T23 refresh at `5b57cf4` recorded p50/p95/p99 165.89/620.51/962.22 ms and 70.49 RPS while moving the dominant observed frames to tenant/YAML/metadata work. | None | None | Composite dossier expanded after the original date. The later flamegraph window includes profiling overhead and is not directly comparable with the unprofiled baseline. Historical src/serving paths and line numbers are not current ownership. Local-development evidence only; not a CI or cross-host benchmark, not a current-code benchmark, and not a production SLA or production acceptance. `production.status` remains `candidate`. |
| [entity-profile-after-pii-masker-cache.md](../perf/entity-profile-after-pii-masker-cache.md) | 2026-04-24 | Point-in-time PII-masker cache result at `220f94c` with the same recorded local fixture and 2000-request contract: p50/p95/p99 56.65/233.78/360.97 ms, 193.73 RPS, 2000/2000 successes, and a reported -61% p99 delta from the initial baseline. | None | None | Point-in-time result, not a stable current baseline. The later dossier refresh recorded 962.22 ms p99 in a different profiled and noisy window. Explanations for the larger-than-predicted magnitude remain source-stated hypotheses, not proved causes beyond the cache-key fix. Not a CI or cross-host benchmark, production SLA, or production acceptance; `production.status` remains `candidate`. |
| [entity-profile-after-tenant-qualification-cache.md](../perf/entity-profile-after-tenant-qualification-cache.md) | 2026-04-25 | Accepted local best-of-3 T24 result with open auth: p50 193.29 -> 113.01 ms, p95 242.42 -> 140.88 ms, p99 288.85 -> 167.14 ms, and 81.10 -> 138.08 RPS, a 42.13% p99 improvement. Despite the noise, the worst after 261.46 ms beat the best before 288.85 ms. | None | None | The Date cell is the creation-commit date; the source has no Date field. It labels HEAD measured `5b57cf4`, while the cache implementation and profile first enter tracked history in `aae27bf`; exact after-run bytes are not commit-bound. Both before/after series had spread above 10%, and hardware and dependency versions are not inherited from the baseline. Historical local evidence only; not a CI or cross-host benchmark, production SLA, or production acceptance. `production.status` remains `candidate`. |

## Historical OpenAPI contract divergence diagnostic

This table catalogues one immutable diagnostic identity for a dated local
OpenAPI contract-test divergence. The record explains a compatibility
normalization; it is not a document supersession chain. Columns are identity,
ISO date, result, supersedes, superseded by, and claim boundary. `None` means
no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [test_openapi_compliance-divergence-2026-04-25.md](../perf/test_openapi_compliance-divergence-2026-04-25.md) | 2026-04-25 | Point-in-time contract-test diagnostic: local Python 3.13.7, FastAPI 0.128.0, Pydantic 2.12.5, and Starlette 0.50.0 added `ValidationError` fields `input` and `ctx` relative to the project `.venv` on FastAPI 0.135.3 and the Docker CI-like line on FastAPI 0.136.1. The project `.venv` passed on Python 3.13.7, ruling out Python 3.13 itself. Normalization was limited to the FastAPI-owned validation-error fields while project-owned schemas and paths remained strict. | None | None | Historical local diagnostic of one FastAPI-version-specific schema divergence. This is not a full Python/FastAPI/Pydantic/Starlette compatibility matrix and does not establish runtime API acceptance, production compatibility, an SLA, or production acceptance; `production.status` remains `candidate`. |

## Historical authentication performance baseline

This table catalogues the point-in-time authentication microbenchmark that
motivated the M-C4 hash-format change and closed M-C5 as not a bottleneck. The
2026-06-05 closure notice was added to the same immutable identity; the
current runbook and implementation narrow where its historical bcrypt result
still applies. They do not create a second evidence identity, so this is not a
document supersession chain. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [auth-bench-2026-05-26.md](../perf/auth-bench-2026-05-26.md) | 2026-05-26 | Historical bcrypt baseline on Intel Ultra 5 125H, Windows 11, and Python 3.13: at `bcrypt_rounds=12` and N=20 over 3 trials, hit-last p95 8146.6 ms and miss-all p95 8221.9 ms; rate-window trim at `rate_limit_rpm=120` over 5,000 calls was p95 0.006 ms. The same record's 2026-06-05 closure notice reports indexed Argon2id hit-last cold at approximately 34 ms and misses at approximately 0.1 ms. | None | None | Point-in-time microbenchmark on a single Windows 11 laptop under the `Cool Limited` power profile, not a served-API benchmark and not a concurrent-load benchmark. The historical bcrypt figures apply to legacy entries without `key_lookup`; current indexed Argon2id keys use O(1) candidate lookup. The current figures are closure-note comparisons, not a production latency SLA. Does not establish production acceptance; `production.status` remains `candidate`. |

## CI performance interpretation records

This table catalogues two point-in-time records that delimit separate CI
performance claims. The 2026-05-24 A03 record calibrated shared-runner gates
against a dated baseline. The 2026-07-09 record later disproved runner speed as
the cause of finding N1's bimodal Load Test and records the request-path
`api_usage` fix. That correction narrows how CI variance may be interpreted;
it does not supersede the A03 document or erase its dated decision. The
records are complementary, so both use `None`/`None`. Columns are identity,
ISO date, result, supersedes, superseded by, and claim boundary.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [ci-hardware-gap-2026-05-24.md](../perf/ci-hardware-gap-2026-05-24.md) | 2026-05-24 | Point-in-time A03 decision: after local entity p99 fell from 936 ms to 167 ms (-82%) and throughput rose from 68 to 138 RPS, the 2026-04-25 shared `ubuntu-latest` baseline remained 600-800 ms for GET and 740-980 ms for POST endpoints. A 1.3x CI headroom was adopted with 900 ms, 1100 ms, and 1200 ms endpoint gates while the local p99 < 200 ms SLO remained unchanged. | None | None | Dated calibration on shared 2-core, 4-7 GB runners. It does not prove every later CI tail is hardware, does not supersede later application-bottleneck findings, and does not authorize future threshold relaxation without the record's re-evaluation triggers. This is not a production latency SLA or production acceptance; `production.status` remains `candidate`. |
| [usage-write-bifurcation-2026-07-09.md](../perf/usage-write-bifurcation-2026-07-09.md) | 2026-07-09 | Finding N1 root cause and fix: three red runs clustered at 29.4, 29.1, and 28.9 RPS (1.7% spread), while nine green runs ranged from 37.0 to 46.2 RPS; a 1.5x RPS change accompanied a 10x p99 change. Synchronous DuckDB `api_usage` commits capped the API at `1/s`; an injected 34 ms write reproduced 31.4 RPS, while the background path held 37.9 RPS and 37.2 RPS at 34 ms and 60 ms. The fix uses a queue, one background writer, and batch commits. | None | None | Corrects only the runner-speed reading of finding N1 and does not supersede the A03 hardware-gap record or deny remaining runner variability. Durability moves after the response, so a crash can lose queued rows; the admin read is affected, but `api_usage` is not billing and not rate limiting. This is not a production throughput SLA or production acceptance; `production.status` remains `candidate`. |

## ARM shared-runner benchmark packet

This table catalogues one immutable benchmark identity: the dated human-authored
summary. Its tracked packet also contains the generated companions
[`docs/perf/arm-benchmark-2026-06-05/arm-benchmark.md`](../perf/arm-benchmark-2026-06-05/arm-benchmark.md),
[`docs/perf/arm-benchmark-2026-06-05/arm-host-metadata.md`](../perf/arm-benchmark-2026-06-05/arm-host-metadata.md),
and
[`docs/perf/arm-benchmark-2026-06-05/arm-current.json`](../perf/arm-benchmark-2026-06-05/arm-current.json).
Those generated companions are protected as the raw packet, not separate
evidence identities. The summary uses `None`/`None`; this packet does not form
a document supersession chain. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [arm-server-benchmark-2026-06-05.md](../perf/arm-server-benchmark-2026-06-05.md) | 2026-06-05 | Dispatch-only workflow run 27012731848 at commit `60e0f3d` on GitHub-hosted `ubuntu-24.04-arm`: Neoverse-N2, 4 vCPU, 15.6 GB RAM, and Python 3.11.15. The canonical DuckDB harness used 50 users, spawn rate 10/s, duration 60 s, and a 10 s warmup. It completed 554 requests with zero failures at 37.41 RPS, aggregate p50 6.0 ms, p95 44.0 ms, and p99 150.0 ms. Every entity release gate passed; worst entity p50 4.0 ms and worst entity p99 150.0 ms. | None | None | Point-in-time result on a shared CI runner, not a dedicated 16-vCPU production host; there is no c8g.4xlarge performance claim. The run used DuckDB and a synthetic seeded fixture. The historical x64 figures are not strictly comparable across hosts and this is not a regression claim. It is not production-class hardware, not a production latency SLA, and not production acceptance; `production.status` remains `candidate`. |

## ClickHouse serving-path verification record

This table catalogues the ADR 0006 Phase 1 serving surface behavior capture.
That Phase 1 serving surface is separate from Phase 2 PII-governance and is not
a supersession relationship: the records verify different contracts on the
same standalone engine family. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [clickhouse-serving-verify-2026-07-02.md](../perf/clickhouse-serving-verify-2026-07-02.md) | 2026-07-02 | ADR 0006 Phase 1/1a live behavior verification against standalone ClickHouse 26.7.1.368 in WSL Ubuntu 22.04, no Docker: pipeline burst 60 was 60/60 valid, orders_v2=13, and pipeline_events=73; the API returned the seeded order, revenue 2799.65, top-3 products with the latest row version, and ClickHouse-only SSE events; a separate-process burst moved revenue to 3279.57, upsert dedup returned exactly 1 row, the dispatcher reported api_ready with 0 dispatcher/scan errors, and tenant-scope transpile had no false positives | None | None | Single-node, single-writer demo profile with auth disabled; it does not prove multi-writer version ordering. Kafka/Flink health remained placeholder-unhealthy in this bring-up. No equivalent p50/p95 was measured: this verifies behavior and is not a latency figure. Phase 2 PII-governance is a separate surface, not a supersession. Does not establish production SLA or production acceptance; `production.status` remains `candidate`. |

## ClickHouse PII-governance verification records

This table is the audit catalogue for the two standalone ClickHouse 26.7
live-verification captures of the ADR 0006 Phase 2 PII boundary. The
2026-07-03 capture refreshes the 2026-07-02 capture on the current seeds and
checked-in probe set. It supersedes the earlier capture only as the latest
ClickHouse live verification outcome. Historical facts remain valid. The
separate PostgreSQL verification line measures another engine and is not part of this
supersession chain. Columns are identity, ISO date, result, supersedes,
superseded by, and claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [vault-pii-governance-verify-2026-07-02.md](../perf/vault-pii-governance-verify-2026-07-02.md) | 2026-07-02 | ADR 0006 Phase 2 live verification on standalone ClickHouse 26.7.1.368: 32/32 probes passed against a 2,000-customer demo vault (msk 800 / dxb 200); analyst PII shapes were denied, officers remained jurisdiction-scoped, admin was unaffected, and the PII-safe subquery workaround plus idempotent governance DDL were verified | None | [vault-pii-governance-verify-2026-07-03.md](../perf/vault-pii-governance-verify-2026-07-03.md) | Historical first ClickHouse capture on a standalone WSL synthetic-seed stand. Superseded only as the latest current-seed/current-script outcome; the dated findings remain valid. Does not claim the separate PostgreSQL line, promoted CDC volume, a separated production admin identity, an external penetration test, or production acceptance; `production.status` remains `candidate`. |
| [vault-pii-governance-verify-2026-07-03.md](../perf/vault-pii-governance-verify-2026-07-03.md) | 2026-07-03 | Current ClickHouse refresh on standalone 26.7.1.492 with the current kitchen-gadget seeds and checked-in probe set: 29/29 passed, 0 FAIL / 0 WARN, with 2,500 customers (msk 2,190 / dxb 60) and all PII-denial and jurisdiction assertions green | [vault-pii-governance-verify-2026-07-02.md](../perf/vault-pii-governance-verify-2026-07-02.md) | None | Current ClickHouse live evidence for the checked-in script on a standalone synthetic-seed stand, not promoted CDC. The applying `default` admin sees everything, and the production identity split remains unverified. Does not supersede the separate PostgreSQL evidence or claim cross-engine/Kubernetes deployment, an external penetration test, or production acceptance; `production.status` remains `candidate`. |

## PostgreSQL PII-governance verification records

This table is the audit catalogue for the two standalone PostgreSQL 17.5
live-verification captures of the ADR 0006 Phase 2 PII boundary. The
2026-07-03 capture refreshes the 2026-07-02 capture on the current seed legend
and checked-in probe set. It supersedes the earlier capture only as the latest
PostgreSQL live-verification outcome. Historical facts remain valid. This is a
PostgreSQL-only chain; neither row supersedes the separate ClickHouse records.
Columns are identity, ISO date, result, supersedes, superseded by, and claim
boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [vault-pii-governance-pg-verify-2026-07-02.md](../perf/vault-pii-governance-pg-verify-2026-07-02.md) | 2026-07-02 | First standalone PostgreSQL 17.5 capture: 33/33 probes passed on a deterministic 10-row demo seed (msk 8 / dxb 2); column ACL denial, officer row scoping, PostgreSQL default-deny RLS, owner bypass, and four-file idempotent governance re-apply were verified | None | [vault-pii-governance-pg-verify-2026-07-03.md](../perf/vault-pii-governance-pg-verify-2026-07-03.md) | Historical standalone Windows throwaway stand with a deterministic demo seed, not promoted CDC. The admin/owner sees all data, and the production identity split remains unverified. The dbt marts and `bv_order_canonical_mat` exist only on ClickHouse and are outside this record. Does not establish cross-engine/Kubernetes deployment, an external penetration test, production SLA, or production acceptance; `production.status` remains `candidate`. |
| [vault-pii-governance-pg-verify-2026-07-03.md](../perf/vault-pii-governance-pg-verify-2026-07-03.md) | 2026-07-03 | Current PostgreSQL 17.5 kitchen-gadget/current-prefix refresh: 33/33 probes passed, 0 FAIL / 0 WARN, on a deterministic 10-row demo seed (msk 8 / dxb 2); `1c__msk`, `pg_ops__msk`, and `mp__msk` were exercised, and all four governance files re-applied idempotently | [vault-pii-governance-pg-verify-2026-07-02.md](../perf/vault-pii-governance-pg-verify-2026-07-02.md) | None | Current standalone Windows throwaway-stand evidence with a deterministic demo seed, not promoted CDC. The admin/owner sees all data, and the production identity split remains unverified. The dbt marts and `bv_order_canonical_mat` exist only on ClickHouse and are outside this record. Does not establish cross-engine/Kubernetes deployment, an external penetration test, production SLA, or production acceptance; `production.status` remains `candidate`. |

## PostgreSQL control-plane and canonical-order verification records

This table catalogues two point-in-time PostgreSQL live-verification records
for separate runtime surfaces. They are complementary, not a supersession
chain: one verifies control-plane persistence and concurrency, while the other
verifies canonical-order view reconstruction. They ran on different PostgreSQL
versions and hosts and do not establish an integrated deployment. Columns are
identity, ISO date, result, supersedes, superseded by, and claim boundary.
`None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [control-plane-pg-verify-2026-07-03.md](../perf/control-plane-pg-verify-2026-07-03.md) | 2026-07-03 | Standalone PostgreSQL 17.5 control-plane live verification: 31/31 probes passed in 19.45s with psycopg 3.3.4; 8 threads produced one enqueue winner, 4 threads claimed without duplicates or loss, and restart re-drive, outbox/dead-letter rollback atomicity, alert-tick single-flight, two app boots sharing state, and `api_usage` persistence passed | None | None | Point-in-time standalone Windows trust auth stand, not a production deployment. The adapter uses no pooling and one connection per method; pooling remains a follow-up. Two sequential app boots do not prove an actual multi-pod rollout. This is not an SLA or production acceptance; `production.status` remains `candidate`. |
| [bv-order-canonical-pg-smoke-2026-07-06.md](../perf/bv-order-canonical-pg-smoke-2026-07-06.md) | 2026-07-06 | PostgreSQL 16.14 canonical-order live smoke on Mac Colima/Docker: 17/17 assertions passed, 0 FAIL, over 8 deterministic orders; the 197166.67 total, SCD2 latest-wins collapse, soft-delete tombstone, pricing on 7 of 8 orders, and jurisdiction VAT at 5% and 20% matched the hand-verified contract | None | None | Point-in-time standalone seed smoke, not promoted CDC. The end-to-end CDC-to-serving variant remains open, and this view-logic run was not integrated with the control plane. It does not establish PostgreSQL 17.5 execution, production SLA, or production acceptance; `production.status` remains `candidate`. |

## NL-to-SQL evaluation records

This table catalogues two point-in-time results from the same 18-question
harness and normalised gold set. They are complementary engine configurations,
not a supersession chain: one measures the shipped rule-based default, while
the other measures the opt-in GraceKelly/Sonnet path. Columns are identity, ISO
date, result, supersedes, superseded by, and claim boundary. `None` means no
supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [nl-sql-eval-2026-07-01.md](../perf/nl-sql-eval-2026-07-01.md) | 2026-07-01 | Shipped default rule-based translator on the fixed in-memory DuckDB harness: overall 27.8% (5/18), in-pattern 62.5% (5/8), and out-of-pattern 0.0% (0/10); three in-pattern misses exposed fixed-projection brittleness, while all ten out-of-pattern questions were untranslated | None | None | Point-in-time direct translator harness, not the served endpoint. Time windows were a deliberate no-op, so time-window precision was not tested; the `/query` PII deny-gate was also outside scope. The immutable source's companion cross-reference still says 88.9%; the companion record owns the final 100.0% post-normalisation outcome. This is not a production benchmark, SLA, or production acceptance; `production.status` remains `candidate`. |
| [nl-sql-eval-sonnet5-2026-07-01.md](../perf/nl-sql-eval-sonnet5-2026-07-01.md) | 2026-07-01 | Opt-in Sonnet 5 via GraceKelly: 100.0% (18/18) overall, 100.0% (8/8) in-pattern, and 100.0% (10/10) out-of-pattern; each question used a single generation pass with no repairs, taking about 11-24 s per question and 4.5 min wall-clock total | None | None | Point-in-time direct translator result on 18 curated demo questions, not a benchmark. It is live and non-deterministic and not pinned in CI; GraceKelly is opt-in, while the shipped default remains rule-based. Time windows were a no-op and the served `/query` PII deny-gate was outside scope. This is not a production accuracy benchmark, SLA, or production acceptance; `production.status` remains `candidate`. |

## Historical streaming-hop freshness record

This table catalogues the dated Kafka-to-Flink streaming-hop measurement that
preceded the complete serving bridge. It remains a separate measurement
segment, not a supersession relationship: S8 extends the measured path through
the serving stack and owns the current full event-to-metric claim without
erasing the earlier hop-only observation. Columns are identity, ISO date,
result, supersedes, superseded by, and claim boundary. `None` means no
supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [freshness-realpath-2026-06-30.md](../perf/freshness-realpath-2026-06-30.md) | 2026-06-30 | Historical streaming-hop-only measurement on `deproject-mac`, macOS 13.7.8 / Intel i5-7500, Colima 6 GiB / 4 CPU, Flink 2.2.1-java17, Kafka 7.7.0, and Python 3.11.15: n=30 with 0 misses from `orders.raw` to `events.validated`; p50 2.50 s, p95 10.11 s, p99 15.42 s, and mean 3.33 s | None | None | Historical streaming-hop-only observation of `orders.raw` to `events.validated`. It does not include the serving bridge, ClickHouse, Redis, or API and is not event-to-metric evidence. S8 remains the current full-path claim owner and extends the measured path; this is not a supersession because the segment remains separately valid. Measured on a single-node Mac/Colima stand; not an SLA, a cross-host benchmark, or production acceptance. `production.status` remains `candidate`. |

## Current freshness evidence records

This table is the audit catalogue for the current real-path freshness claim
and the complementary in-process demo-path baseline. They measure different
execution scopes and are not a supersession chain: S8 owns the
Kafka-to-live-metric claim, while the generated demo report remains the
shortcut baseline
and explicitly records that its pre-S7 invalidation wiring is historical.
Columns are identity, ISO date, result, supersedes, superseded by, and claim
boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [freshness-e2e-realpath.md](../perf/freshness-e2e-realpath.md) | 2026-07-09 | S8 real-path event-to-live-revenue-metric measurement: p50 3.02 s, p95 5.70 s, n=20 with one miss, across Kafka -> Flink -> bridge -> ClickHouse -> Redis invalidation -> API | None | None | Measured on a single Mac/Colima stand for the revenue metric, with one miss. This is not an SLA, a cross-host production benchmark, the demo shortcut, or production acceptance; `production.status` remains `candidate`. |
| [freshness-benchmark.md](../perf/freshness-benchmark.md) | 2026-06-06 | Generated in-process DuckDB shortcut pre-S7: `event_driven` p50 1.06 s and p95 1.99 s, n=30, on Windows with fakeredis-backed cache semantics | None | None | Does not measure Kafka, Flink, bridge, or ClickHouse and does not claim current production invalidation wiring, a production SLA, or production acceptance. This is a Windows/fakeredis demo-path baseline; the S8 real-path record is complementary. |

## E4 replica-correctness evidence records

This table is the audit catalogue for the baseline two-pod control-plane proof
and its complementary extension through automated Checks 1-4.
It is not a supersession chain: the later record adds delivery and alert
assertions on a different kind snapshot. The earlier record retains the
unique explicit A-to-B pod probe. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [e4-2pod-topology-2026-07-09.md](../perf/e4-2pod-topology-2026-07-09.md) | 2026-07-09 | PASS for Checks 1-2: two ready pods using the PostgreSQL control plane; webhook visible on all 8 round-robin Service reads; explicit A-to-B registration/list probe on kind `hq-demo` | None | None | Does not claim Checks 3-4, exactly-once delivery, alert single-page, production availability, or production acceptance. The later Checks 1-4 record uses a different kind snapshot and does not supersede this explicit A-to-B proof. |
| [e4-check4-alert-single-page-2026-07-17.md](../perf/e4-check4-alert-single-page-2026-07-17.md) | 2026-07-17 | Checks 1-4 PASS on kind `agentflow-staging`: 2/2 ready, webhook visible on 8 reads, exactly one delivery ID, and exactly one alert history row | None | None | Local pre-push main with a staging image and external httpbin target. Does not claim durable persistence, production availability or SLA, or production acceptance. It extends the automated checks but does not supersede the unique `hq-demo` A-to-B proof. |

## Historical E4 intermediate replica-correctness records

This table is the audit catalogue for two historical intermediate
replica-correctness proofs that sit between the already indexed
current E4 records: the 2026-07-09 `hq-demo` Checks 1-2 snapshot and
the 2026-07-17 Checks 1-4 `agentflow-staging` snapshot. These records
are historical intermediate topology evidence, not current status
owners. They are an extension of automated check coverage, not a supersession chain:
the 2026-07-11 record closes the two-real-pods
Checks 1-2 layer on kind `agentflow-staging` after the 2026-07-06
resource-blocked attempt; the 2026-07-16 record completes the
exactly-one delivery half that Checks 1-2 left open. The later Checks
1-4 record extends the same script with alert single-page and does
not supersede these intermediate snapshots. Neither record supersedes
the unique `hq-demo` A-to-B proof. Columns are identity, ISO date,
result, supersedes, superseded by, and claim boundary. `None` means
no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [e4-replica-topology-2026-07-11.md](../perf/e4-replica-topology-2026-07-11.md) | 2026-07-11 | PASS for Checks 1-2 on kind `agentflow-staging` at `9935bdc`: 2/2 ready postgres pods; webhook `4a4709a0-0bdc-42bc-803a-2d49c1fb8f04` visible on all 8 round-robin reads; closes the 2026-07-06 blocked Phase 3 topology attempt | None | None | Historical intermediate topology proof only. Does not claim Checks 3-4, exactly-one delivery, alert single-page, or production acceptance. Completes the two-real-pods Checks 1-2 layer on `agentflow-staging` after the 2026-07-06 resource-blocked attempt; it does not supersede the unique `hq-demo` A-to-B proof. Later Check 3 and Checks 1-4 records extend automated coverage and do not supersede this snapshot. `production.status` remains `candidate`. |
| [e4-check3-exactly-one-delivery-2026-07-16.md](../perf/e4-check3-exactly-one-delivery-2026-07-16.md) | 2026-07-16 | Checks 1-3 PASS on kind `agentflow-staging` at `22fbae6`: 2/2 ready, webhook visible on 8 reads, exactly one delivery_id for event_id=replica-e4-858cce874ac04494 | None | None | Historical intermediate Check 3 proof only. Completes the delivery half that Checks 1-2 left open; it is an extension, not a supersession of the 2026-07-11 topology record. Does not claim Check 4, alert single-page, or production acceptance. The later Checks 1-4 record extends the automated script with alert single-page and does not supersede this exactly-one delivery snapshot. Not a current status owner; `production.status` remains `candidate`. |

## Current endurance and scale evidence records

This table is the audit catalogue for the current four-hour real-path
plus API-read endurance claim and the complementary generated own-data
scale proof. They measure different execution scopes and are not a supersession chain:
S11 owns the produce → Flink → `events.validated` →
serving bridge → ClickHouse path plus steady API reads, while S13 owns
in-database generation of the project's own legend at 51.2 M rows.
S13 explicitly records that streaming ingestion numbers live in the
throughput-realpath and S11 records. The later
[rss-reverify-183-2026-07-11.md](../perf/rss-reverify-183-2026-07-11.md)
is a scoped partial supersession of S11's API RSS leak finding only; it
does not supersede the S11 full-path endurance claim. Columns are
identity, ISO date, result, supersedes, superseded by, and claim
boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [soak-s11-2026-07-10.md](../perf/soak-s11-2026-07-10.md) | 2026-07-10 | S11 4 h real-path plus API-read endurance: ~47 eps avg, hourly lag 71/44/134/0 bounded, peak lag 2 915 during one Kafka session timeout then drained to 0, bridge RSS sawtooth 38→114→11 MB with FDs 94–95, one 256-event batch replayed exactly-once by the journal guard, zero cache drift (API 1 540 429 855.37 == ClickHouse) | None | [rss-reverify-183-2026-07-11.md](../perf/rss-reverify-183-2026-07-11.md) | Current status owner for four-hour real-path plus API-read endurance on the deproject-mac Colima 6 GiB/4 CPU stand. Driver-side shortfall (682 679 of 720 000 applied) is not serving-path loss. Later [rss-reverify-183-2026-07-11.md](../perf/rss-reverify-183-2026-07-11.md) is a scoped partial supersession of the API RSS finding (175 MB → 1.67 GB) only; it does not supersede this full-path endurance claim. Not a production SLA or production acceptance; `production.status` remains `candidate`. |
| [scale-own-data-2026-07-11.md](../perf/scale-own-data-2026-07-11.md) | 2026-07-11 | S13 generated own-data scale: 51.2 M rows / 2.87 M orders / 4 years of legend history, analyst queries 20–730 ms, all 17 at-scale correctness checks pass | None | None | Current status owner for generated own-data scale only. In-database generation (`INSERT … SELECT FROM numbers()`) on a single-node laptop-class VM; 845 k rows/s is generator + ClickHouse write, not streaming ingestion. Customer-PII / loyalty / product-catalog satellites stay demo-scale. Does not prove the S11 endurance soak, a production SLA, or production acceptance; `production.status` remains `candidate`. |

## API RSS fix re-verification record

This table is the audit catalogue for the STATUS-linked live re-verification
of the API RSS fix for issue #183. It is a scoped partial supersession of
S11's API RSS leak finding only. The full-path endurance claim remains
S11-owned: the re-verification exercised the same bridge, ClickHouse journal,
dispatcher cursor, and API-read surface, but the Flink hop was bypassed during
the growth phase. Columns are identity, ISO date, result, supersedes,
superseded by, and claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [rss-reverify-183-2026-07-11.md](../perf/rss-reverify-183-2026-07-11.md) | 2026-07-11 | API RSS fix live re-verification on deproject-mac: 97 min / 98 one-minute samples; journal 1.371 M rows at start and 1.732 M after growth; API RSS 77.3 MB → 100.9 MB, full-window slope +7.5 MB/h and growth-phase slope +3.2 MB/h; quartile Q4 below Q3; 185 MB maximum transient reclaimed; FDs 149–152; reads 1 149 / 1 149 HTTP 200 with 0 errors; issue #183 closed live | [soak-s11-2026-07-10.md](../perf/soak-s11-2026-07-10.md) | None | Scoped partial supersession of S11's API RSS leak finding only; full-path endurance remains S11-owned. The Flink hop was bypassed and fresh events entered directly at `events.validated`, so this 97-minute API/bridge-surface re-verification is not a four-hour full-path soak, not a production SLA, and not production acceptance. `production.status` remains `candidate`. |

## Current S10 throughput evidence records

This table is the audit catalogue for the two current STATUS-linked
S10 throughput endpoints: the retained pre-Q1.2 canonical burst
baseline and the 2026-07-19 four-hour paced serving-path PASS.
They measure different modes and are not a direct supersession chain.
`throughput-realpath.md` is the explicitly retained pre-Q1.2 canonical
S10 burst baseline, not the later best sustained rate and not the
current freshness headline. r4 is the current four-hour paced-gate
outcome; r1/r3 historical facts remain valid. The later F-02 decision
explicitly preserves r4 as the already-closed serving-path gate while
the broader golden full-soak plus rollback gate remains open. Do not
merge those gates or imply production acceptance. Columns are
identity, ISO date, result, supersedes, superseded by, and claim
boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath.md](../perf/throughput-realpath.md) | 2026-07-09 | pre-Q1.2 canonical S10 unpaced burst baseline: 400 events, produce 699 events/s, Flink hop 7.97 events/s, bridge apply 7.97 events/s, duplicates 0, apply failures 0, lag 0 → 0 / peak 329 | None | None | Explicitly retained pre-Q1.2 canonical S10 burst baseline on deproject-mac Colima vz 6 GiB / 4 CPU. Different mode from the later four-hour paced r4 PASS; not a direct supersession chain. Not the later best sustained rate (q13/q14/100eps/10m/1h remain separately evidenced) and not the current freshness headline. Not a production SLA or production acceptance; `production.status` remains `candidate`. |
| [throughput-realpath-paced100-4h-r4-2026-07-19.md](../perf/throughput-realpath-paced100-4h-r4-2026-07-19.md) | 2026-07-19 | S10 four-hour paced serving-path PASS: produced = delivered = 1 440 000 at 100.0 eps, Flink hop 99.9 eps (1 440 000 validated), bridge apply 99.9 eps (+1 440 000 unique), consumed = applied = 1 440 000, duplicates 0, apply failures 0, lag 0 → 0 (peak 1956), Flink never restarted (checkpoints restored 0, completed 484/484, failed 0), disk ≤ 74 % | [throughput-realpath-paced100-4h-2026-07-18.md](../perf/throughput-realpath-paced100-4h-2026-07-18.md) [throughput-realpath-paced100-4h-r3-2026-07-19.md](../perf/throughput-realpath-paced100-4h-r3-2026-07-19.md) | None | Current four-hour paced-gate outcome only; r1/r3 historical facts remain valid. F-02 preserves r4 as the already-closed serving-path gate while the broader golden full-soak plus rollback gate remains open. Pre-materializer Kafka→Flink→bridge→ClickHouse path on deproject-mac Colima vz 6 GiB / 4 CPU / 60 GiB; advisory for the post-Iceberg golden gate, which remains `BLOCKED_HOST_CAPACITY`. Different mode from the pre-Q1.2 burst baseline; not a direct supersession chain. Does not merge those gates or claim a production SLA or production acceptance; `production.status` remains `candidate`. |

## Historical four-hour paced S10 predecessor records

This table is the audit catalogue for the r1 and r3 predecessors of the
current four-hour paced r4 result. They preserve distinct failure modes and
are not a supersession chain: r1 failed after stand disk exhaustion, while r3
failed because the harness counted messages that never reached Kafka. r4
supersedes both only as the current four-hour paced-gate outcome; their
historical facts remain valid. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath-paced100-4h-2026-07-18.md](../perf/throughput-realpath-paced100-4h-2026-07-18.md) | 2026-07-18 | Historical r1 FAIL measured 2026-07-18T00:23:20Z → 05:03:25Z on deproject-mac at `05afb32`: 1 440 000 produced at 100.0 eps; 1 424 309 validated including replays at 84.8 eps; 1 132 164 unique applied at 67.4 eps; failures / duplicates 0 / 292 145; lag 0 → 0 / peak 1939; stand disk reached 99–100 %, checkpoint failures caused 116 restarts, and the TaskManager container died with exit 127; journal dedup reconciled exactly as 1 424 309 = 1 132 164 + 292 145 | None | [throughput-realpath-paced100-4h-r4-2026-07-19.md](../perf/throughput-realpath-paced100-4h-r4-2026-07-19.md) | Historical stand disk exhaustion result, not an apply-path defect. The path was healthy for about 2.5 h before disk exhaustion; multi-hour sustained >=100 eps remains open for this attempt. r4 supersedes r1 as the current four-hour paced-gate outcome only; historical facts remain valid. Pre-materializer serving path only; does not close the golden full-soak plus rollback gate, which remains `BLOCKED_HOST_CAPACITY`, or establish a production SLA or production acceptance. `production.status` remains `candidate`. |
| [throughput-realpath-paced100-4h-r3-2026-07-19.md](../perf/throughput-realpath-paced100-4h-r3-2026-07-19.md) | 2026-07-19 | Historical r3 formal FAIL measured 2026-07-19T01:26Z → 06:07Z on deproject-mac at `05afb32`: benchmark counted 1 440 000 paced events in 14 430 s, but only 1 031 462 reached Kafka and 408 538 were lost client-side; Flink validation and bridge apply each processed 100 % of delivered events; failures / duplicates 0 / 0; lag 0 → 0 / peak 2015; 0 restarts and 578/578 completed checkpoints; process duration 4.7 h but actual delivered load only 2 h 52 m; disk peaked at 73 % | None | [throughput-realpath-paced100-4h-r4-2026-07-19.md](../perf/throughput-realpath-paced100-4h-r4-2026-07-19.md) | Historical harness delivery-accounting failure after 16 s broker fencing, with 408 538 lost client-side; the serving path processed every delivered event exactly once. Actual load for 2 h 52 m does not prove four hours, so multi-hour sustained >=100 eps remains open for this attempt. r4 supersedes r3 as the current four-hour paced-gate outcome only; historical facts remain valid. Pre-materializer serving path only; does not close the golden full-soak plus rollback gate, which remains `BLOCKED_HOST_CAPACITY`, or establish a production SLA or production acceptance. `production.status` remains `candidate`. |

## Q1.2 predecessor S10 throughput record

This table is the audit catalogue for Q1.2, the root of the narrow
Q1.2 -> Q1.3 -> Q1.4 chain of 400-event apply-path optimization outcomes.
Q1.2 does not supersede the separately retained pre-Q1.2 baseline. Q1.3
supersedes Q1.2 only as the later result in this narrow chain; historical
measurements remain valid. Columns are identity, ISO date, result, supersedes,
superseded by, and claim boundary. `None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath-q12-2026-07-09.md](../perf/throughput-realpath-q12-2026-07-09.md) | 2026-07-09 | Historical intermediate Q1.2 400-event unpaced warm canonical re-measure at 2026-07-09T18:00:02+00:00 on deproject-mac, code `5a7ed6f` / `skip_local_store`, no scratch DuckDB, Colima 6 GiB / 4 CPU, API not started: produce 217 eps; Flink hop = bridge apply = 11.4 eps; applied / duplicates / failures 400 / 0 / 0; catch-up 35.2 s; peak lag 213; about 1.4x the pre-Q1.2 apply baseline; >=80 target missed | None | [throughput-realpath-q13-2026-07-09.md](../perf/throughput-realpath-q13-2026-07-09.md) | Historical intermediate Q1.2 root of the narrow 400-event optimization chain. The cold run was noisy; the warm canonical result shows removing scratch DuckDB was not a 10x win, with the honest product number still in the low tens. It does not claim hundreds of events/s: 217 eps produce is host/driver variance and not the product ceiling. Q1.2 does not supersede the pre-Q1.2 baseline; Q1.3 supersedes it as the later apply-path outcome only. Does not establish sustained throughput, a production SLA, or production acceptance. Golden full-soak plus rollback remains open; `production.status` remains `candidate`. |

## Q1.3/Q1.4 intermediate S10 throughput records

This table is the audit catalogue for two intermediate S10 400-event
unpaced burst records on the ClickHouse-only apply path. They form a
narrow q12 -> q13 -> q14 supersession chain only as later 400-event
apply-path optimization outcomes. Historical measurements remain valid.
Do not merge this narrow chain with the current four-hour paced-gate
chain. Q1.4 is the current `docs/STATUS.md`/README owner for the
400-event Q1.4 burst outcome, but remains an intermediate point in the
broader S10 series. Later 2000-event 107.3-eps drain and paced 10m/1h/r4
records measure different windows/modes and are not direct supersessions
of this 400-event burst result. Columns are identity, ISO date, result,
supersedes, superseded by, and claim boundary. `None` means no
supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath-q13-2026-07-09.md](../perf/throughput-realpath-q13-2026-07-09.md) | 2026-07-09 | Q1.3 intermediate 400-event unpaced burst measured 2026-07-09T18:08Z on deproject-mac; code q13-ch-batch-apply at 88a3de4 / 5bd2189; ClickHouse-only bridge path, no DuckDB; produce 647 eps, Flink hop = bridge apply = 22.9 eps; failures 0, catch-up 17.5 s, peak lag 218; about 2.9x the original S10 apply baseline and 2.0x Q1.2; quality-plan target >=80 eps still missed | [throughput-realpath-q12-2026-07-09.md](../perf/throughput-realpath-q12-2026-07-09.md) | [throughput-realpath-q14-2026-07-10.md](../perf/throughput-realpath-q14-2026-07-10.md) | Q1.3 is an intermediate optimization measurement, not a sustained-rate, production SLA, production acceptance, or current-best claim. Supersedes Q1.2 only as the later 400-event apply-path optimization outcome and is superseded by Q1.4 on that same narrow outcome. Historical measurements remain valid. Do not merge this narrow chain with the current four-hour paced-gate chain. Golden full-soak plus rollback remains open; `production.status` remains `candidate`. |
| [throughput-realpath-q14-2026-07-10.md](../perf/throughput-realpath-q14-2026-07-10.md) | 2026-07-10 | Q1.4 intermediate 400-event unpaced burst measured 2026-07-10 on deproject-mac, Colima vz 6 GiB / 4 CPU, macOS 13.7.8 Intel, one Flink TaskManager; code main at 13a242d; ClickHouse-only bridge path, no DuckDB; produce 376 eps, Flink hop = bridge apply = 87.4 eps; failures / duplicates 0 / 0, catch-up 4.58 s, peak lag 0; 3.8x Q1.3 and 11x the original S10 apply baseline; quality-plan target >=80 eps met on this burst profile; batch amortization 10 non-empty batches / 800 events, mean 80, p50 >32 | [throughput-realpath-q13-2026-07-09.md](../perf/throughput-realpath-q13-2026-07-09.md) | None | Q1.4 is the current `docs/STATUS.md`/README owner for the 400-event Q1.4 burst outcome, but remains an intermediate point in the broader S10 series. It does not establish sustained >=100 eps, a multi-hour rate, production SLA, or production acceptance. The later 2000-event 107.3-eps drain and paced 10m/1h/r4 records measure different windows/modes and are not direct supersessions of this 400-event burst result. Historical measurements remain valid. Do not merge this narrow chain with the current four-hour paced-gate chain. Golden full-soak plus rollback remains open; `production.status` remains `candidate`. |

## Paced 10-minute and one-hour S10 throughput records

This table is the audit catalogue for two STATUS-linked paced-duration
milestones on the same 100 eps target protocol. The canonical record date
is 2026-07-17; each result retains its exact measured UTC window. The
10-minute and one-hour records are a duration-extension sequence, not a
supersession chain, and historical facts remain valid. Neither replaces
the separate finite 2000-event drain record. The four-hour r4 record
remains the current four-hour paced-gate outcome and does not erase these
shorter milestones. Columns are identity, ISO date, result, supersedes,
superseded by, and claim boundary. `None` means no supersession is
recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath-paced100-2026-07-17.md](../perf/throughput-realpath-paced100-2026-07-17.md) | 2026-07-17 | 10-minute paced duration milestone measured 2026-07-16T22:52–23:03Z on deproject-mac, Colima vz 6 GiB / 4 CPU, code main at 4631299, Kafka → Flink with one Flink TaskManager → bridge → ClickHouse; 60 000 produced at 100.0 eps over 600.0 s, 60 000 validated at 97.1 eps, bridge apply +59 654 at 96.5 eps over 618.1 s including catch-up, failures / duplicates 0 / 0, lag 0 → 0 / peak 1037; first paced gate PASS | None | None | First paced duration milestone in a duration-extension sequence with the one-hour run, not a supersession chain; historical facts remain valid. The source attributes the 59 654 versus 60 000 applied delta likely to end-of-window metric accounting or residual journal visibility; this row does not claim all 60 000 applied. Not a multi-hour result. The separate 2000-event drain measures another mode, while four-hour r4 remains the current paced-gate outcome. Pre-materializer serving path only; does not close the golden full-soak plus rollback gate, which remains `BLOCKED_HOST_CAPACITY`. Not a production SLA or production acceptance; `production.status` remains `candidate`. |
| [throughput-realpath-paced100-1h-2026-07-17.md](../perf/throughput-realpath-paced100-1h-2026-07-17.md) | 2026-07-17 | one-hour paced duration milestone measured 2026-07-16T23:30Z → 2026-07-17T00:30Z on deproject-mac, Colima vz 6 GiB / 4 CPU, code main at b5d9ce0, Kafka → Flink with one Flink TaskManager → bridge → ClickHouse; 360 000 produced at 100.0 eps over 3600.0 s, 360 000 validated and Flink hop 99.5 eps, bridge apply +360 000 at 99.5 eps over 3617 s including catch-up, failures / duplicates 0 / 0, lag 0 → 0 / peak 1679; one-hour gate PASS | None | None | One continuous hour and a distinct paced duration milestone, not multi-hour and not a supersession chain; historical facts remain valid. It extends duration beyond the 10-minute proof without replacing it. The separate 2000-event drain measures another mode, while four-hour r4 remains the current paced-gate outcome. Pre-materializer serving path only; does not close the golden full-soak plus rollback gate, which remains `BLOCKED_HOST_CAPACITY`. Not a production SLA or production acceptance; `production.status` remains `candidate`. |

## Finite 2000-event S10 drain record

This table is the audit catalogue for the STATUS-linked finite 2000-event
unpaced produce + catch-up drain measurement. It is a single drain window,
not a sustained or paced-ingress result. Q1.4, this drain, and the paced
10-minute, one-hour, and four-hour r4 records measure different windows and
are not a supersession chain; historical facts remain valid. Columns are
identity, ISO date, result, supersedes, superseded by, and claim boundary.
`None` means no supersession is recorded.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [throughput-realpath-100eps-try-2026-07-17.md](../perf/throughput-realpath-100eps-try-2026-07-17.md) | 2026-07-17 | finite 2000-event produce + catch-up drain measured 2026-07-16T22:28–22:29Z on deproject-mac, Colima vz 6 GiB / 4 CPU, macOS 13.7.8 Intel; code Mac checkout 88c9804 with the Q1.4 apply path; ClickHouse-only Kafka → Flink with one Flink TaskManager → `events.validated` → host bridge → ClickHouse; produce 2216 eps, Flink hop = bridge apply = 107.3 eps, failures / duplicates 0 / 0, catch-up wall 18.65 s, peak lag 187; >=100 numeric stretch bar met for this single drain window | None | None | Finite produce + catch-up drain capacity observation only, not a sustained >=100 eps result, paced-ingress window, multi-hour rate, production SLA, or production acceptance. Does not supersede Q1.4's 400-event burst or the 10-minute, one-hour, and four-hour r4 paced records; they measure different windows/modes, and historical facts remain valid. Pre-materializer ClickHouse-only serving path; does not close the golden full-soak plus rollback gate, which remains `BLOCKED_HOST_CAPACITY`. `production.status` remains `candidate`. |

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

## Golden soak cross-run causal analysis

This table catalogues the read-only causal analysis across consumed golden-soak
attempts `-01` through `-05`. It is complementary to the canonical
[`-05` outcome](../perf/golden-4h-soak-05-failure-2026-08-08.md): the RCA
preserves cross-run confidence levels and retention gaps but does not supersede
that current latest-soak record or change its claim ownership. The RCA uses
`None`/`None` because analysis is not a document supersession relationship.
Columns are identity, ISO date, result, supersedes, superseded by, and claim
boundary.

| Identity | Date | Result | Supersedes | Superseded by | Claim boundary |
| --- | --- | --- | --- | --- | --- |
| [golden-4h-soak-failures-01-05-rca-2026-08-09.md](../perf/golden-4h-soak-failures-01-05-rca-2026-08-09.md) | 2026-08-09 | Read-only RCA of five consumed soak attempts `-01` through `-05`: no soak PASS, no `dual_mean_90` PASS JSON, and corrected Helm rollback not started. Runs `-01`/`-02` show high-confidence shared VM/control-plane disruption but unresolved exact exceptions; `-03` admitted a `RUNNING 0/2` job; `-04` proves a container-runtime/control-plane infrastructure failure and Kafka data loss as a post-collapse recovery blocker; `-05` produced 1,440,000/1,440,000 at 99.99979 EPS before terminal Flink failure and remains `UNRESOLVED_FLINK_TERMINAL_FAILURE`. Guest-clock backward jumps appear in every failure window. | None | None | Complementary to the canonical `-05` report, not a supersession. It does not prove that a clock jump alone caused `-01`, `-02`, or `-05`; does not relabel `-05` as producer failure, Kafka failure, OOM, verifier load, or pod-topology failure; and does not claim one exact Flink exception across all five attempts. The P0 Kafka exceptions are post-failure recovery evidence. Identities `-01` through `-05` are consumed. This record does not authorize a rerun, live remediation, Helm rollback, production elevation, push, or identity reuse; `production.status` remains `candidate`. |

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
