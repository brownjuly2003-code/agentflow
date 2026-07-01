# Demo → ClickHouse serving cutover — execution plan

Implements **ADR 0006** (fix serving engine on ClickHouse) and unblocks
**ADR 0007** (K8s horizontal API scaling). This is the "how", the ADRs are the
"why". Scope: move the shipped serving path from DuckDB to ClickHouse, make PII
bounded on the engine, and turn on real K8s scaling. DuckDB stays as the
local-dev / test store.

## What already exists (no work)

- `src/serving/backends/clickhouse_backend.py` — real HTTP backend, MergeTree
  demo tables, `duckdb→clickhouse` sqlglot transpile, injection-safe literals.
- `src/serving/backends/__init__.py` — `create_backend` factory, `SERVING_BACKEND`
  env override.
- `docker-compose.prod.yml` — `--profile clickhouse` service.
- `docs/clickhouse-migration.md` — operator switch guide.
- NL→SQL model already updated to `claude-sonnet-5` (`nl_engine._llm_translate`).

## Phase 1 — Fix the engine default (config, reversible)

Flip the shipped default from `duckdb` to `clickhouse`. This is config-only and
reversible (`SERVING_BACKEND=duckdb` rolls back).

- [ ] `config/serving.yaml` → `backend: clickhouse`.
- [ ] `docker-compose.prod.yml` → make the `clickhouse` service part of the
      default demo bring-up (not just `--profile clickhouse`), or document that
      the demo command now includes it. Keep `SERVING_BACKEND` overridable.
- [ ] `docker-compose.e2e.yml` — decide: run E2E against ClickHouse (closest to
      shipped) or keep DuckDB for speed and add a ClickHouse E2E lane. Recommend a
      ClickHouse E2E lane so the shipped path is covered.
- [ ] Verify: `SERVING_BACKEND=clickhouse` local bring-up, `/v1/health` green,
      `test_query_package_logic.py::...clickhouse` path passes, entity + metric +
      `/v1/query/explain` return correct rows (parity with DuckDB).

## Phase 2 — Make PII bounded on the engine (the point of the cutover)

> **Scope correction (2026-07-01).** This phase originally targeted the serving
> demo tables, but those hold **no PII** — the app-level `assert_no_pii_access`
> gate and the entity redactor guarded an empty surface and have since been
> removed (see CHANGELOG). Real contact PII lives only in the **DV2 business vault**
> (`warehouse/agentflow/dv2/business_vault/bv_customer_mdm__*.sql`), so this phase
> applies ClickHouse row/column policies **to the vault**, not to the serving
> `users_enriched`/`orders_v2`. The bullets below that reference the app-level gate
> or `X-PII-Masked` are obsolete; the row/column-policy bullet is the live plan.

Replace string-shape denial with engine-enforced policy on the vault tables that
actually carry PII.

- [ ] Introduce a **schema-execution** check for the PII gate: resolve the actual
      output columns/types of a candidate query against ClickHouse
      (`DESCRIBE` / `LIMIT 0`) and require them to be ⊆ non-PII, recursing through
      structs. This is engine ground-truth, not SQL-form guessing.
- [ ] Apply **ClickHouse row/column policies** (`CREATE ROW POLICY` /
      column-level `GRANT`) for PII tables so non-exempt tenants cannot read PII
      columns even if a query slips the app-level gate. DuckDB has no equivalent —
      this is why the cutover is what makes PII bounded.
- [ ] Reclassify the app-level gate honestly: it becomes defense-in-depth in
      front of an engine-enforced boundary, not the boundary itself. Update the
      `assert_no_pii_access` docstring + `docs/architecture.md` note + CHANGELOG.
- [ ] Verify: the 3 historical bypass forms (COLUMNS-expr, whole-row struct-ref,
      column-rename-list) are denied by the engine policy regardless of app gate;
      exempt tenants unchanged; `X-PII-Masked` contract preserved.

## Phase 3 — Turn on K8s horizontal scaling (ADR 0007)

Only valid once serving is external (Phase 1). Do not do this while backend is
DuckDB.

- [ ] `helm/agentflow/values.yaml` — set serving to ClickHouse (drop
      `config.duckdbPath` from the request path; point at the ClickHouse service
      via `CLICKHOUSE_HOST` etc. / `SERVING_BACKEND=clickhouse`). Keep
      `usageDbPath` only if the usage store still needs it.
- [ ] Remove the request-path write PVC dependency; confirm pods are stateless.
- [ ] Enable `autoscaling` with sane `minReplicas`/`maxReplicas` and an HPA CPU
      target; remove the `replicaCount: 1` hard-pin.
- [ ] Add a `values.schema.json` / comment note: `autoscaling` requires an
      external serving engine.
- [ ] Verify: `scripts/k8s_staging_up.sh` on kind, `k8s_smoke_test.sh` green,
      `replicaCount: 2` schedules without PVC contention.

## Phase 4 — NL→SQL (routes through GraceKelly)

- [x] LLM path routes through the **GraceKelly orchestration API**
      (`${GRACEKELLY_URL}/api/v1/orchestrate`), model `claude-sonnet-5` — no
      direct provider SDK. Gate + engine detection realigned to `GRACEKELLY_URL`
      across `nl_engine`, `nl_queries`, `analytics`, `agent_query`.
- [x] **GraceKelly serves Sonnet 5.** `claude-sonnet-5` resolves through the GK
      orchestration API today — no GK-side upgrade needed.
- [ ] Prompt dialect: **keep DuckDB-flavored** (backend transpiles). Documented
      in ADR 0006.
- [ ] LLM reachability: the shipped demo runs the **rule-based** translator
      because `GRACEKELLY_URL` is unset in every deploy config. To make the LLM
      path live, point `GRACEKELLY_URL` at a reachable GraceKelly instance
      (compose/K8s config, never a secret in code); otherwise leave rule-based.
      Product choice, not a code bug.

## Phase 5 — Docs, changelog, gates

- [ ] `docs/architecture.md` — replace the "serving engine is not fixed" open-
      decision block with the decided state (link ADR 0006/0007).
- [ ] `docs/clickhouse-migration.md` — reframe from "optional switch" to
      "default engine; DuckDB is the local-dev/test store".
- [ ] `CHANGELOG.md [Unreleased]` — serving default → ClickHouse, PII now
      engine-enforced (behavior/contract note), NL→SQL model → Sonnet 5.
- [ ] Full verify: unit + integration (ClickHouse lane) green, ruff/mypy clean,
      mutation gates re-targeted if the PII module moves.

## Rollback

- Phases 1 and 3 are config-only reversible (`SERVING_BACKEND=duckdb`,
  `autoscaling.enabled=false`, `replicaCount=1`).
- Phase 2 is **not** cleanly reversible — the PII redesign changes the boundary
  semantics. Land it behind the same tests as the current gate and keep the
  app-level gate as defense-in-depth so a rollback of the engine policy still
  denies the known forms.

## Gate before starting

This plan changes a security boundary (Phase 2) and a shipped default (Phase 1).
Confirm scope with the owner before executing Phase 2 — it is the irreversible
part. Phase 1 alone (engine default flip) is low-risk and can go first.
