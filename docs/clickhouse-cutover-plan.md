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

## Phase 1 — Fix the engine default (config, reversible) — **EXECUTED 2026-07-02**

Flip the shipped default from `duckdb` to `clickhouse`. This is config-only and
reversible (`SERVING_BACKEND=duckdb` rolls back).

- [x] `config/serving.yaml` → `backend: clickhouse` (owner decision 2026-07-02:
      the demo runs on ClickHouse).
- [x] `docker-compose.prod.yml` → `clickhouse` service is part of the default
      bring-up (profile gate removed, API `depends_on` its healthcheck);
      `docker-compose.yml` gained the service for `make demo`; `SERVING_BACKEND`
      stays overridable.
- [x] `docker-compose.e2e.yml` — a ClickHouse E2E lane so the shipped path is
      CI-covered. Done 2026-07-02: the E2E stack ships a `clickhouse` service,
      the API boots the shipped serving profile against it, and the workflow
      asserts post-run that ClickHouse holds the seeded serving tables (the API
      seeds them only on the ClickHouse profile, so rows there prove no silent
      DuckDB fallback). Verified green via `workflow_dispatch` on the branch
      (run 28552265071).
- [x] Verify: live single-binary ClickHouse bring-up — `/v1/health` green,
      entity + metric + NL query parity, and the cross-process freshness loop
      (pipeline writes CH → dispatcher scan → cache invalidation). See
      `docs/perf/clickhouse-serving-verify-2026-07-02.md`.

### Phase 1a — Make the flip *coherent* (added by the 2026-07-02 audit) — **EXECUTED**

The original plan flipped reads but left the event→metric axis on DuckDB: no
writer fed ClickHouse and the webhook/invalidate/SSE scans polled the embedded
connection — the core freshness property would have silently died on the
shipped engine.

- [x] `src/processing/clickhouse_sink.py` — the local pipeline mirrors serving
      tables + the `pipeline_events` journal to ClickHouse when it is the
      configured backend (DuckDB stays the local lake/test store).
- [x] Upsert model: mutable serving tables are `ReplacingMergeTree` versioned
      by a MATERIALIZED `af_updated_at`; every backend read runs with `final=1`.
- [x] `QueryEngine.fetch_pipeline_events` — the freshness-critical scan goes
      through the serving backend; webhook dispatcher and SSE delegate to it.
- [x] Transpile safety net: `_translate_sql` fails closed if a table reference
      (incl. the tenant schema qualifier) does not survive the rewrite.

## Phase 2 — Make PII bounded on the engine (the point of the cutover) — **EXECUTED 2026-07-02**

> **Scope correction (2026-07-01).** This phase originally targeted the serving
> demo tables, but those hold **no PII** — the app-level `assert_no_pii_access`
> gate and the entity redactor guarded an empty surface and have since been
> removed (see CHANGELOG). Real contact PII lives only in the **DV2 business vault**
> (`warehouse/agentflow/dv2/business_vault/bv_customer_mdm__*.sql`), so this phase
> applies ClickHouse row/column policies **to the vault**, not to the serving
> `users_enriched`/`orders_v2`.

Replace string-shape denial with engine-enforced policy on the vault tables that
actually carry PII.

- [x] Apply **ClickHouse row/column policies** (`CREATE ROW POLICY` /
      column-level `GRANT`) for PII tables so non-exempt principals cannot read
      PII columns. Done: `warehouse/agentflow/dv2/governance/` — `dv2_analyst`
      fail-closed allow-list (contact-PII columns never granted, PII satellites
      not granted), per-jurisdiction `dv2_pii_officer__<branch>` roles, row
      policies scoping `rv.hub_customer` + mandatory catch-all;
      `bv_customer_mdm__*` flipped to `SQL SECURITY DEFINER` so the column
      grants work without exposing the personal satellites;
      `marts.customer_360` made PII-free by contract. DuckDB has no
      equivalent — this is why the cutover is what makes PII bounded.
- [x] Verify: the 3 historical bypass forms (COLUMNS-expr, whole-row struct-ref,
      column-rename-list) are dead at the engine — `COLUMNS` resolves to real
      columns and hits the missing grant (`ACCESS_DENIED`); the other two are
      not expressible on ClickHouse at all (`UNKNOWN_IDENTIFIER`). All 29
      adversarial probes green on a live 26.7 server, incl. jurisdiction
      row-scoping and admin-unaffected checks:
      `docs/perf/vault-pii-governance-verify-2026-07-03.md`.
- ~~Introduce a schema-execution check for the PII gate~~ /
  ~~Reclassify the app-level gate~~ — obsolete: the app-level gate was removed
  with the serving PII layer (2026-07-01); there is no app-side PII surface
  left to gate. The engine policy above IS the boundary. `X-PII-Masked` stays
  a reserved header (versioning contract), untouched by this phase.

## Phase 3 — Turn on K8s horizontal scaling (ADR 0007 + ADR 0009/0010)

Only valid once serving is external (Phase 1) **and** the control plane is
external (ADR 0010 rollout: webhook queue/log, alert rules+history,
outbox/dead-letter, usage behind `ControlPlaneStore`, PostgreSQL adapter
live-verified). Do not do this while backend is DuckDB or while
`controlPlane.store=embedded` — the chart now **fails any multi-replica
render** until both halves of the gate are set, so this phase cannot be
executed accidentally.

- [x] Prerequisite: ADR 0010 slices 1–5 merged (`PostgresControlPlaneStore`
      exists, live-verified); slice 6 extends the values schema so
      `controlPlane.store=postgres` renders. *(Done 2026-07-04, slice 6: the
      `store` enum now admits `postgres`, `controlPlane.postgres.{existingSecret,dsnKey}`
      carries the DSN, and `templates/deployment.yaml` wires
      `AGENTFLOW_CONTROLPLANE_STORE` + `AGENTFLOW_CONTROLPLANE_PG_DSN` — E4.)*
- [x] Chart profile — the scale profile is now expressible **as an overlay**,
      not by editing the shipped `values.yaml` (whose default stays the
      zero-dependency DuckDB/embedded demo): `k8s/staging/values-staging-scale.yaml.example`
      sets `serving.backend=clickhouse` (+ `CLICKHOUSE_HOST` etc.),
      `controlPlane.store=postgres` + DSN secret, and drops the DuckDB request
      path. `usageDbPath` retires with ADR 0010 slice 4 (usage already in the
      store). *(Done 2026-07-04, E4.)*
- [x] Request-path PVC dependency removed in the scale profile: the overlay
      sets `persistence.enabled=false`, so with the control plane external there
      is no writable volume left on the request path (ADR 0007 "stateless pods"
      becomes literally true). *(Done 2026-07-04, E4.)*
- [x] `autoscaling` renders an HPA in the scale profile (min/max + CPU target);
      the chart carries no `replicaCount: 1` hard-pin — the default is 1 but any
      value is admissible once both gate halves are set. *(Done 2026-07-04, E4:
      `test_full_scale_profile_admits_autoscaling_hpa`.)*
- [x] Add a `values.schema.json` / comment note: `autoscaling` requires an
      external serving engine. *(Done 2026-07-02, strengthened beyond a note:
      the schema pinned `controlPlane.store` to `embedded` until the adapter
      shipped, and `templates/deployment.yaml` fails any multi-replica render
      unless `controlPlane.store=postgres` and `serving.backend=clickhouse` —
      see ADR 0010. Slice 6 (2026-07-04) released the enum ratchet to
      `[embedded, postgres]`.)*
- [x] **LIVE verify (kind, Docker) — DONE 2026-07-11.** The two-real-pods
      replica-correctness proof passes on a freed VM: `replicaCount: 2` scheduled
      without PVC contention, both pods on the postgres store, and a webhook
      registered via the Service was visible on all 8 round-robin reads across the
      two pods (no split-brain) — `scripts/k8s_replica_correctness_verify.sh`
      Checks 1–2, exit 0. Canon: `docs/perf/e4-replica-topology-2026-07-11.md`.
      Exactly-one delivery / one-alert-per-incident are covered at the store level
      (31/31, slice-5 PG probe); their two-pod emission harness is the remaining
      optional layer. First attempted 2026-07-06 and blocked by host resource
      contention — kept below as honest history.
      *(Chart-side render verified locally 2026-07-04 via `helm template`/
      `lint`, and re-verified live-adjacent on the Mac 2026-07-06: `helm lint`
      clean; `helm template --set replicaCount=2 --set persistence.enabled=false`
      **without** `controlPlane.store=postgres`/`serving.backend=clickhouse`
      correctly fails at render time with the exact ADR 0010 gate error
      (`"Multi-replica requires BOTH an external serving engine ... AND an
      external control-plane store ..."`); the same render **with both halves
      set** succeeds with `replicas: 2` and the correct
      `AGENTFLOW_CONTROLPLANE_STORE`/`SERVING_BACKEND` env vars. The
      **two-real-pods live run** (building `agentflow/api`, deploying 2 pods,
      exercising `scripts/k8s_replica_correctness_verify.sh` against them) was
      attempted on the Mac kind stand but could not complete: this same
      session hit severe, sustained shared-host resource contention (the
      Mac runs this kind cluster alongside another project's ~9 containers;
      `/proc/loadavg` read 40–78 for extended stretches, `docker stats` showed
      a co-tenant's Temporal engine alone at up to 80% CPU, and this cluster's
      own control plane was crash-looping — `kube-apiserver` had restarted 10+
      times, `kube-controller-manager` 46+ times, confirmed via `crictl ps -a`
      directly on the node). Two separate `docker build` attempts for the
      fresh `agentflow/api` image (needed since the cached image predates
      ADR 0010 slice 5) stalled at near-zero CPU progress even after killing
      a competing orphaned build process. This is an honest "attempted,
      blocked by host resource crisis" outcome — not fabricated, and not
      abandoned without cause; the render-gate logic itself is now more
      thoroughly verified than before. Re-attempt on a quieter window on this
      host, or a dedicated instance.)*

### Phase 3 replica-correctness verify recipe (ADR 0010 slice 6)

Bring up the scale stand (kind + in-cluster PostgreSQL + ClickHouse + Redis and
their secrets), install the chart with the scale overlay, then:

1. **>=2 pods on the postgres store + cross-pod registration visibility** —
   automated by `scripts/k8s_replica_correctness_verify.sh` Checks 1–2: asserts the
   deployment runs ≥2 ready pods all carrying `AGENTFLOW_CONTROLPLANE_STORE=postgres`,
   registers one webhook through the Service, and confirms it is visible on
   every round-robin read (on the embedded YAML store a read served by the pod
   that did not register would miss it — the sharpest split-brain, class 5).
   Live evidence: [perf/e4-replica-topology-2026-07-11.md](perf/e4-replica-topology-2026-07-11.md).
2. **Exactly-one delivery per (webhook, event)** — automated by the same script
   as **Check 3**: inserts one `pipeline_events` row into the shared ClickHouse
   journal (both pods scan it), then asserts `GET /v1/webhooks/{id}/logs` has
   exactly one distinct `delivery_id` for that `event_id` (idempotent enqueue
   insert-win — only the winner POSTs). Live evidence:
   [perf/e4-check3-exactly-one-delivery-2026-07-16.md](perf/e4-check3-exactly-one-delivery-2026-07-16.md).
3. **One alert page per incident** — automated as **Check 4** in the same
   script: creates an `error_rate` rule that fires on the shared journal
   (condition `below` / threshold `1.0` after the Check 3 insert), waits for
   both pods' alert dispatchers to race `claim_alert_tick`, then asserts
   `GET /v1/alerts/{id}/history` has exactly one successful `alert.triggered`
   delivery (not one per pod). Default wait is `ALERT_WAIT_SECONDS=150` (the
   dispatcher polls every 60s). Live evidence:
   [perf/e4-check4-alert-single-page-2026-07-17.md](perf/e4-check4-alert-single-page-2026-07-17.md)
   (Checks 1–4 together on the scale stand).

The **store-level guarantee** behind Checks 2–3 (idempotent enqueue,
single-flight tick, outbox↔dead-letter atomicity) is already live-verified by
the slice-5 standalone-PostgreSQL probe suite (31/31,
`docs/perf/control-plane-pg-verify-2026-07-03.md`) — Phase 3 adds the
two-real-pods topology layer on top.

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
