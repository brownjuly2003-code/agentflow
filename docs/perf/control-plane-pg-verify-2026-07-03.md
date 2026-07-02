# Control plane on PostgreSQL — live verification (ADR 0010 rollout slice 5)

**Date:** 2026-07-03
**Environment:** standalone PostgreSQL 17.5 (EDB windows-x64 binaries, no
Docker, no service install: `initdb` + `pg_ctl`, port 55433, trust auth,
user/db `agentflow`) — the same no-Docker standalone-PG recipe that verified
the vault governance layer
(`vault-pii-governance-pg-verify-2026-07-02.md`). Adapter under test:
`src/serving/control_plane/postgres.py` (`PostgresControlPlaneStore`),
driven by the probe suite the ADR names for this slice:
`tests/integration/test_control_plane_postgres_live.py` with
`AGENTFLOW_TEST_PG_DSN=postgresql://agentflow@127.0.0.1:55433/agentflow`.

**Result: 31/31 probes passed** (`pytest`, 19.45s; psycopg 3.3.4). The same
suite runs in CI against the `postgres:17` service container added to the
`test-integration` job (it self-skips when the DSN env var is absent, the
`test_clickhouse_backend_live.py` pattern).

## The ADR's named probes

| Probe (ADR 0010 § Rollout 5) | Test | Result |
| --- | --- | --- |
| Enqueue-win uniqueness | 8 threads race `enqueue_webhook_delivery` on one (webhook, event) → exactly **1** `True`, 1 row | passed |
| Parallel claim exclusivity | 4 threads claim 10 due rows concurrently → no row handed out twice, none lost (`FOR UPDATE SKIP LOCKED`) | passed |
| Lease-expiry re-drive | row claimed with a 0.4s lease, owner "crashes" → invisible while leased, claimable again after expiry; outcome writes clear the lease so backoff alone governs | passed |
| Restart re-drive | pending row enqueued by one store instance is claimed by a **fresh** instance, canonical body verbatim | passed |
| Outbox↔dead-letter atomicity (invariant 8) | `mark_outbox_sent` flips both rows in one transaction; with `dead_letter_events` dropped mid-scenario the outbox flip **rolls back** (row stays `pending`); `enqueue_outbox_replay` rolls back symmetrically | passed |
| Alert-tick single-flight (§2) | second claimant loses; `complete_alert_tick` persists the advanced record and releases in one transaction; a stale claim self-expires; a concurrent CRUD full-set save does **not** release an in-flight claim | passed |

## Contract parity sweep

Every port method exercised against live PostgreSQL with the same assertions
the embedded adapter's unit pins make: webhook outcome state machine
(backoff → `dead` at max, success → `delivered`, park), oldest-first claim
ordering under `limit`, attempt-log and alert-history roundtrips (newest
first, JSON payload decoded), webhook-registration and alert-rule
repositories (order preserved via a `position` column, full-set save =
YAML-replace semantics, ids required), dead-letter reads (tenant scoping,
reason filter, pagination, stats + trend), usage accounting (per tenant /
per key / old-key-slot hour window), session analytics (idempotent
insert-or-replace on `request_id`, usage/top-queries/top-entities/latency
percentiles/anomalies/QPS shapes, malformed window → `ValueError`, QPS
degrades to 0.0 on an unreachable server).

## End to end: the app itself on the postgres profile

`test_app_on_postgres_profile_shares_state_across_boots` boots the real
FastAPI app twice with `AGENTFLOW_CONTROLPLANE_STORE=postgres`:

- boot #1 resolves `PostgresControlPlaneStore` in the lifespan,
  `AuthManager.store` **is** the shared app-wide store (slice 5 injection in
  `main.py`), and `POST /v1/webhooks` registers a webhook;
- boot #2 (a second pod, in production terms) sees that registration through
  `GET /v1/webhooks` — the class-5 per-pod YAML split-brain is gone;
- `api_usage` rows for the authenticated tenant landed in PostgreSQL, not in
  a local DuckDB file.

## Notes

- Claim leases default to 300s (`AGENTFLOW_CONTROLPLANE_LEASE_SECONDS`
  overrides); alert-tick leases are 120s (`AlertDispatcher.tick_lease_seconds`).
- Payload columns are TEXT holding JSON strings — callers see the same
  "string, you decode it" shape as on the embedded adapter.
- One connection per method call, no pooling (out of ADR 0010 scope,
  recorded follow-up).
