# AgentFlow v1.1.0 to v2.0.0 release narrative

- Original location: `README.md`, `Status` section
- Archived: 2026-08-26
- Reason: the repository README duplicated long-form release history
- Current sources: [`CHANGELOG.md`](../../CHANGELOG.md) and
  [`docs/STATUS.md`](../STATUS.md)
- Content type: historical release narrative

The `v1.1.0` → `v2.0.0` arc landed in seven increments on top of a security
audit-closure sprint:

- **`v1.1.0`** — audit closure: tenant isolation across every read
  surface, SQL guard centralized on `sqlglot`, entity allowlist
  enforcement, fail-closed auth, secret rotation, Helm hardening,
  OpenAPI drift gate, and the required status checks.
- **`v1.2.0`** — DV2 multi-branch warehouse: 55 Data Vault 2.0 tables
  (8 hubs / 8 links / 39 satellites; 64 tables / 48 satellites today), an Argo Workflows `dv2-refresh`
  template, a dbt project (3 mart models + 12 tests), and per-branch CDC
  fan-out via ClickHouse `MaterializedPostgreSQL`.
- **`v1.3.0`** — `helm/kafka-connect` hardening matched to `helm/agentflow`
  (NetworkPolicy + PDB + securityContext), live Helm validation across both
  charts, and the narrated DV2 demo (terminal + web-UI + dbt docs).
- **`v1.4.0`** — maintenance: on-call runbooks, `SECURITY.md`, issue/PR
  templates, contract/DORA CI hardening, repo hygiene, and a dependency
  wave (`mypy`, Terraform AWS provider, TypeScript, GitHub Actions,
  Vitest). No runtime API changes from `v1.3.0`.
- **`v1.5.0`** — security & correctness hardening: argon2id key hashing
  with an O(1) peppered lookup index (M-C4), an NL→SQL guard bypass fix
  (typed `read_csv` / `read_parquet` scan functions now denied in
  projection position), `sqlglot` control-byte and mutation-target
  repairs, and a strict-`mypy` expansion across the orchestration and
  freshness slices. No public API changes.
- **`v1.6.0`** — the architecture-fixing release: ClickHouse becomes the
  shipped serving engine (pipeline sink, `ReplacingMergeTree` row versions,
  backend-routed event scan, a dedicated CI E2E lane against a real
  ClickHouse), PII protection moves from the removed app-level string-parse
  gate to engine-enforced vault governance (fail-closed column grants,
  per-jurisdiction officer roles, row policies, `SQL SECURITY DEFINER`
  views — every live adversarial probe green), plus the vendored NL→SQL
  generation engine (LangGraph, routed through GraceKelly), the DV2 raw
  vault on PostgreSQL with `LISTEN`/`NOTIFY` freshness, the MinIO-backed
  PyIceberg catalog, and the OpenSSF Scorecard channel (5.8 → 7.0).
- **`v2.0.0`** — the demo universe re-founded and the scale path shipped:
  the business legend re-pinned end-to-end to an own-brand
  kitchen-appliance importer in ₽ (breaking for the retired
  fashion-retail/USD surfaces), the external real-retailer dataset removed
  outright (breaking: loader deleted, its at-scale benchmark retired as
  historical), the control plane externalized to PostgreSQL behind the
  `ControlPlaneStore` port (ADR 0010, six slices incl. the Helm scale
  profile), three operational read surfaces split out of the agent catalog
  (ADR 0011: Order 360, stuck-orders worklist, exception inbox), and the
  three-node demo topology (ADR 0012) implemented and deployed to Hugging
  Face Spaces (the `center` hub and the `spb` edge answer live; `ekb` and
  the standalone demo Space are paused — the free tier caps how many
  `cpu-basic` Spaces one account runs at once, and other projects hold the
  rest) — plus the G2 audit closure (spec/seed
  consistency, journal-scan hardening, live evidence re-captures).

The registries remained on published line `v2.0.0`; the post-v2 tree prepared
the unpublished lockstep `v2.1.0` release. Consult current status before using
that historical statement as present truth.
