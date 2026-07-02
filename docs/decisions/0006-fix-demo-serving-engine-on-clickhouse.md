# ADR 0006: Fix the demo serving engine on ClickHouse

## Status

Accepted - 2026-07-01

## Context

The serving layer is pluggable behind the `ServingBackend` ABC
(`src/serving/backends/__init__.py`), with two real implementations: DuckDB
(`duckdb_backend.py`) and ClickHouse (`clickhouse_backend.py`). The engine is
selected at runtime by `SERVING_BACKEND` env → `config/serving.yaml: backend` →
default `"duckdb"`.

Today the engine is **not fixed**. DuckDB is the default everywhere:

- `config/serving.yaml: backend: duckdb`
- `docker-compose.prod.yml: SERVING_BACKEND: ${SERVING_BACKEND:-duckdb}`
- `helm/agentflow/values.yaml: config.duckdbPath: /data/agentflow.duckdb`

ClickHouse is opt-in (`SERVING_BACKEND=clickhouse`, `--profile clickhouse`).

Leaving the engine unfixed is not a neutral default — the whole serving stack is
written in the **DuckDB dialect**, and ClickHouse is bolted on as a transpiler at
the very edge. `ClickHouseBackend._translate_sql` parses each statement as
`read="duckdb"`, rewrites the AST, and regenerates it as `dialect="clickhouse"`
**after** the query has already passed the guard. This produces four concrete
architectural mismatches, all rooted in the same unfixed decision:

1. **DuckDB is the native dialect end to end.** The semantic layer, the
   rule-based NL translator (`nl_engine._rule_based_translate`), and the LLM
   system prompt (`nl_engine._llm_translate`) all emit DuckDB SQL. ClickHouse is
   a translation layer, not a first-class target.
2. **The PII guard is dialect-pinned.** `sql_guard` parses SQL with
   `dialect="duckdb"`, so it cannot be a security boundary when a swappable
   engine executes a different dialect and the ClickHouse backend rewrites the
   SQL *after* the guard runs. This was the root cause of the repeated PII bypass
   findings. **Update (2026-07-01):** the serving-layer PII deny-gate has since
   been removed entirely — the demo serving warehouse holds no PII (see CHANGELOG),
   so it guarded an empty surface. Real PII lives only in the DV2 business vault,
   and Phase 2 below re-homes its governance onto the engine there (ClickHouse
   row/column policies) rather than a dialect-pinned string parse.
3. **Kubernetes horizontal scaling is decorative under DuckDB.** The Helm chart
   ships autoscaling, HPA target CPU, PodDisruptionBudget, and anti-affinity, but
   `config.duckdbPath` puts an embedded DuckDB file on a ReadWriteOnce PVC.
   ReadWriteOnce allows exactly one writing pod, so `replicaCount > 1` is
   impossible; `autoscaling` is hard-pinned `min = max = 1`.
4. **NL→SQL is DuckDB-shaped.** The LLM prompt hard-codes "SQL generator for
   DuckDB" / "Use DuckDB SQL syntax".

## Options considered

### 1. Keep DuckDB as the default serving engine (status quo)

Pros:

- zero migration work; the local demo is a single self-contained file
- no external ClickHouse dependency in the default compose profile

Cons:

- leaves all four mismatches above unresolved
- PII cannot be made bounded on this path (DuckDB has no row/column policies)
- the K8s scaling story stays fictional
- "the architecture is undecided" remains true, which is itself the debt

### 2. Fix the demo and production serving engine on ClickHouse

Pros:

- one decided engine; the transpiler stops being load-bearing for correctness
- bounded PII becomes reachable via ClickHouse-native row/column policies
- stateless API pods + an external ClickHouse service make K8s scaling real
- aligns the serving tier with the industrial-grade ingestion/processing tier
  (Kafka RF3, Flink exactly-once, Iceberg)

Cons:

- ClickHouse becomes a required dependency of the demo (heavier compose)
- requires a migration of config, compose, Helm, and the PII boundary
- local one-command demo now needs a container, not just a file

### 3. Remove pluggability and support ClickHouse only

Rejected: DuckDB is genuinely useful as a zero-dependency local dev/test store
and as the compatibility store for components that read `query_engine._conn`
directly. Deleting it trades a small conceptual simplification for a worse
developer experience with no product benefit.

## Decision

Fix the **demo and production serving engine on ClickHouse**. DuckDB is demoted
from "default serving engine" to **local-dev / test store and compatibility
store** — still first-class for `pytest` and offline development, no longer the
shipped serving path.

Concretely:

- `config/serving.yaml`, `docker-compose.prod.yml`, and
  `helm/agentflow/values.yaml` default to `clickhouse`.
- The PII boundary moves **onto the engine**: schema-execution against ClickHouse
  (`DESCRIBE` / `LIMIT 0`) plus ClickHouse row/column policies, instead of
  dialect-pinned string parsing in `sql_guard`. Bounded, not best-effort.
  **Update (2026-07-02, Phase 2 executed):** delivered as engine RBAC on the
  vault — `warehouse/agentflow/dv2/governance/` (fail-closed allow-list for
  `dv2_analyst` with contact-PII columns never granted, per-jurisdiction
  `dv2_pii_officer__<branch>` roles, row policies on `rv.hub_customer`),
  `SQL SECURITY DEFINER` on `bv_customer_mdm__*`, and a PII-free-by-contract
  `marts.customer_360`. The separate schema-execution app check became moot
  when the app-level gate was removed with the empty serving PII surface:
  access control on resolved columns *is* the engine ground-truth. Verified
  live, 32/32 adversarial probes:
  `docs/perf/vault-pii-governance-verify-2026-07-02.md`.
- The semantic layer **keeps emitting DuckDB-flavored SQL** and relies on
  `ClickHouseBackend._translate_sql` to transpile — this stays a deliberate,
  documented layer rather than an accident. Making the semantic layer emit
  ClickHouse-native SQL is out of scope for this ADR (it would remove the
  transpiler but couple every query site to one engine); revisit only if the
  transpiler proves insufficient.
- NL→SQL LLM path runs **through the GraceKelly orchestration API**
  (`${GRACEKELLY_URL}/api/v1/orchestrate`), never a direct provider SDK.
  GraceKelly owns model selection/execution (browser-backed **Sonnet 5**,
  `GRACEKELLY_NL_SQL_MODEL=claude-sonnet-5`, which GraceKelly serves today, so the
  requested model resolves through the GK API). Prompt dialect stays
  DuckDB-flavored because the backend transpiles.

## Consequences

### Positive

- the serving engine is decided; the transpiler is no longer a correctness crutch
- PII can be made bounded (engine-native policies)
- K8s horizontal API scaling becomes real (stateless pods + external ClickHouse)
- serving is no longer a different weight class from the rest of the platform

### Negative

- ClickHouse is now a required demo dependency; the default compose is heavier
- one-command "just a file" local demo is replaced by a container bring-up
- a migration is required across config, compose, Helm, PII, and docs

## Follow-up

- Execute `docs/clickhouse-cutover-plan.md` (config/compose/helm cutover, PII
  redesign, verification). *Status 2026-07-02: Phases 1, 1a and 2 executed;
  Phase 3 (K8s scaling, gated on ADR 0009) and Phase 5 doc sweep remain.*
- See ADR 0007 for how this unblocks Kubernetes horizontal scaling.
- Keep DuckDB green in CI as the local-dev/test store; do not delete it.
- The PostgreSQL port of the vault (`warehouse/agentflow/dv2/postgres/`) has
  the same MDM views but no governance analog yet (PG RLS + column grants);
  follow-up, not shipped — see `governance/README.md`.
