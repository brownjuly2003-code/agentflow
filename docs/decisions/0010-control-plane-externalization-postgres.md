# ADR 0010: Control-plane externalization — PostgreSQL behind a ControlPlaneStore port

## Status

Accepted - 2026-07-02 (staged execution; slices tracked in § Rollout)

Resolves the choice deferred by
[ADR 0009](0009-control-plane-state-and-scaling-gate.md) ("pick option 2 or 3
when multi-replica is actually required"). Multi-replica is now actually
required: the owner directed the control plane out of the API pod, the
cutover plan's Phase 3 (HPA) is blocked on it, and the planned multi-node
demo topology needs a control plane that is not pinned to one process.

## Context

ADR 0009 recorded the honest gate: API horizontal scaling needs **both** an
external serving engine (ADR 0006/0007 — executed) **and** control-plane
state that is not embedded per-pod. This ADR decides where that state goes.

### Verified state inventory (at `main=6d4bc32`)

Six classes of per-pod state, all of which fork at `replicaCount > 1`:

| # | State | Where it lives today | Access path |
|---|-------|----------------------|-------------|
| 1 | Webhook delivery queue (`webhook_delivery_queue`) + attempt log (`webhook_deliveries`) | embedded serving DuckDB | `webhook_dispatcher.py:348,470,507,553` via `query_engine._conn`; read by `routers/webhooks.py:112` |
| 2 | Alert history (`alert_history`) | embedded serving DuckDB | `alerts/escalation.py:251`, `alerts/history.py`; read by `routers/alerts.py:157` |
| 3 | Replay outbox (`outbox`) + `dead_letter_events` status transitions | embedded serving DuckDB | `processing/outbox.py` (wired in `main.py:214`), `routers/deadletter.py:67,79`, `processing/event_replayer.py` |
| 4 | Usage accounting (`api_usage`) + sessions (`api_sessions`) | separate per-pod DuckDB file (`AGENTFLOW_USAGE_DB_PATH`), a fresh file connection per request | `auth/usage_table.py`, `analytics.py` |
| 5 | Webhook registrations | per-pod YAML file (`config/webhooks.yaml`) | `webhook_dispatcher.py:31,59-125` |
| 6 | Alert rules **including mutable runtime state** (`state`, `fired_at`, `last_escalation_level`, flap window, cooldown) | per-pod YAML file (`config/alerts.yaml`), rewritten on every changed evaluation tick | `alerts/dispatcher.py:25,266-283` |

Items 5–6 were not in ADR 0009's list; they are the sharpest split-brain of
all — a webhook registered on pod A does not exist on pod B, and N pods run
N independent alert state machines that each page on-call and race the YAML
writes.

Not blockers (already replica-safe, recorded for completeness):

- **Rate limiting** is Redis-backed with a per-process fail-closed fallback
  (`rate_limiter.py`) — shared across replicas whenever Redis is up.
- **Metric-cache invalidation** targets the shared Redis cache and is
  idempotent; per-pod `seen_event_ids` scanning is safe *once the durable
  enqueue below is an atomic claim* (dedup moves to the store's primary key).
- **Serving reads and the freshness event scan** go through the backend
  abstraction since ADR 0006 Phase 1 (`QueryEngine.fetch_pipeline_events`,
  `clickhouse_sink.py`) — the event→metric axis is already engine-external.
  (`routers/lineage.py:74` / `routers/slo.py:64,106` still read serving data
  over `_conn`; that is the serving-read seam from the 2026-07-02 audit §3.6,
  adjacent to but out of scope for this ADR.)

### Durable-delivery invariants the store must preserve

ADR 0009 says the decision "should start from the durable-delivery semantics
pinned by the webhook/alert regression suites". Those pins, by suite:

1. Enqueue is idempotent per `(webhook_id, event_id)` — primary-key dedupe.
2. An event is marked seen only after **every** matching webhook is durably
   enqueued (audit_30 C2); marking seen drives cache invalidation and must
   work with zero webhooks registered.
3. Inline delivery happens only for fresh enqueues; the re-drive path replays
   the stored canonical body verbatim.
4. Outcome state machine: `pending → delivered`, or backoff re-schedule, or
   park as `dead` at `max_delivery_attempts`; a removed/deactivated webhook
   parks rather than retrying forever.
5. Deliveries survive a process restart (a new instance re-drives `pending`).
6. Alert firing/escalation/resolution advance **only on successful delivery**
   (audit_28 #4, audit_30 C1) — a failed page is re-attempted next tick.
7. Escalation advances exactly one level per tick (lowest due level).
8. `outbox` mark-sent flips `dead_letter_events.status='replayed'` **in the
   same transaction**; exhausted retries flip it to `'failed'`
   (`outbox.py:_mark_sent/_schedule_retry`).

Invariant 8 is a genuine cross-table transaction with rollback. Invariants
1/4 need atomic claim semantics as soon as more than one worker exists.

## Options considered

### 1. ClickHouse tables (no new service — CH is already the scale-profile engine)

Rejected. The queue and the alert state machine are mutable row state with
claim semantics; ClickHouse mutations are asynchronous and there are no row
locks — N replicas polling due rows would each deliver the same row
(systematic N× duplicates), and nothing can express invariant 8's
transactional flip. CH remains right for what already lives there
(serving tables, `pipeline_events` journal).

### 2. Redis for queues/state + ClickHouse for history/usage (no new dependency — redis is already an optional import)

Rejected, on semantics rather than taste. Workable for the queue (streams +
consumer groups + `XAUTOCLAIM`), but: invariant 8 becomes a cross-store
consistency gap (queue transitions in Redis, `dead_letter_events` elsewhere —
atomicity only via Lua and hash-tag discipline, and not across stores at
all); the alert state machine needs WATCH/MULTI or Lua for compare-and-set;
history/usage reads are SQL-shaped (`WHERE ts >= now() - INTERVAL 24h GROUP
BY tenant`) and would still need a second store. Two adapters, two failure
domains, and the hardest invariant lands on the weakest tool. Redis keeps
the jobs it already does well here: cache and rate limiting.

### 3. Singleton dispatch worker (leader election / replicas=1 worker Deployment)

Rejected as the *primary* answer. Dispatch loops could be single-flighted,
but control-plane state is written by API pods on the request path too:
usage accounting on **every request**, webhook/alert CRUD, dead-letter
redrive. Those writes need a shared store regardless, or the worker grows an
internal RPC API (a bigger, stateful surface than a store port). It also
leaves the pod with a writable volume, which is exactly what ADR 0007's
"stateless pods" promise is about. A worker Deployment stays available
*later* as a deployment-topology refinement on top of the shared store (move
the loops out of API pods); it is not a substitute for one.

### 4. PostgreSQL behind a store port — chosen

Every invariant maps natively: idempotent enqueue = `INSERT .. ON CONFLICT
DO NOTHING` with insert-win detection; claims = `FOR UPDATE SKIP LOCKED`
with a lease column (work-stealing across replicas, **no leader election
needed**); invariant 8 = an ordinary transaction; alert single-flight = a
per-rule claimed tick; history/usage = plain SQL tables read exactly the way
the routers already query them. Operationally: the CI integration
environment already runs PostgreSQL (CDC path), the repo already carries
deep PG expertise and a proven no-Docker live-verify recipe (standalone
PG 17.5, `docs/perf/vault-pii-governance-pg-verify-2026-07-02.md`), and
`psycopg` slots into the same optional-import pattern `redis` already uses
(no hard dependency for the embedded profile). It also converges the
end-state triad this platform is heading toward anyway: **ClickHouse =
analytics/serving, PostgreSQL = transactional state, Redis = cache/limits.**

Cost, stated honestly: the scale profile gains a required PostgreSQL
service (DSN-configured; the chart will not ship one, mirroring how
ClickHouse is consumed), and `psycopg` joins the optional dependencies.

## Decision

1. **A `ControlPlaneStore` port** (`src/serving/control_plane/`) owns all six
   state classes. Two adapters:
   - `EmbeddedControlPlaneStore` — extracts today's behavior (DuckDB tables
     via the serving connection, YAML files for registrations/rules),
     byte-compatible with existing on-disk formats. Default profile; the
     zero-dependency demo does not change.
   - `PostgresControlPlaneStore` — all six classes as PG tables.
     `psycopg` is imported lazily/optionally (the `redis` pattern).
   Selection: `AGENTFLOW_CONTROLPLANE_STORE=embedded|postgres` +
   `AGENTFLOW_CONTROLPLANE_PG_DSN` (secret-sourced in the chart).
2. **Claim semantics are part of the port contract**, not adapter trivia:
   - `enqueue_*` returns whether *this caller* inserted the row (embedded:
     check-then-insert on one process; PG: `ON CONFLICT DO NOTHING` +
     rowcount) — inline delivery belongs to the enqueue winner only.
   - `claim_due_*` returns rows this worker now owns (embedded: plain
     select; PG: `FOR UPDATE SKIP LOCKED` + `lease_expires_at`; an expired
     lease makes the row due again — crash recovery without coordination).
   - `claim_alert_tick(rule_id, lease)` single-flights each alert rule's
     evaluation across replicas; rule runtime state advances in the same
     transaction as the claim release.
   - outbox `mark_sent` / `mark_failed` keep the `dead_letter_events` flip
     in the same transaction (invariant 8).
3. **At `replicaCount = N`**, the documented semantics are: every pod scans
   events (idempotent; N× read amplification accepted and noted), enqueue
   dedupes on the store, exactly one pod inline-delivers a fresh enqueue,
   re-drive and outbox work is claimed, alert rules evaluate single-flight,
   cache invalidation stays idempotent on shared Redis. Delivery remains
   at-least-once end-to-end (unchanged; consumers already get signed,
   deduplicatable events).
4. **The render gate lands now, ahead of the code** (this change):
   - `values.schema.json` pins `controlPlane.store` to the enum
     `["embedded"]` — the chart cannot *advertise* a profile the app cannot
     run; `"postgres"` joins the enum in the slice that ships the adapter.
   - `templates/deployment.yaml` **fails any multi-replica render**
     (`replicaCount > 1`, or autoscaling enabled with `maxReplicas > 1`)
     unless `controlPlane.store=postgres` **and**
     `serving.backend=clickhouse` — ADR 0007's engine half and ADR 0009's
     control-plane half of the gate, enforced in one place at render time
     instead of a values comment.

## Rollout (each slice = one PR, full suite green, no behavior change before slice 5)

1. Port + `EmbeddedControlPlaneStore`; webhook queue + delivery log move
   behind it (`webhook_dispatcher` stops touching `query_engine._conn`).
2. Alert history + alert rules/runtime-state repository behind the port
   (embedded impl keeps the YAML file format).
3. Outbox + dead-letter behind the port (invariant 8 preserved verbatim).
4. Usage/sessions behind the port — `usage_table.py`, `analytics.py`,
   `key_rotation.py`'s old-key-usage queries and `admin_ui.py`'s QPS tile all
   queried `api_usage`/`api_sessions` directly; all four move behind the port
   (pure extraction, per-request file connections unchanged — pooling is not
   part of this ADR).
5. `PostgresControlPlaneStore` + live verification (standalone-PG probe
   suite: parallel claim exclusivity, lease expiry re-drive, restart
   re-drive, enqueue-win uniqueness, outbox↔dead-letter atomicity) +
   CI integration coverage (a `postgres:17` service added to the CI
   integration job). Executed 2026-07-03 with two scope additions the
   extraction slices had left open, both required for §1's "all six state
   classes" to hold: **webhook registrations** (class 5 — the sharpest
   split-brain — was still a per-pod YAML read outside the port; the
   registration CRUD now resolves the store from ``app``, embedded keeps the
   byte-compatible YAML) and **§2's ``claim_alert_tick`` /
   ``complete_alert_tick``** wired into the dispatcher (per-rule state
   persistence — a full-set save would let two replicas clobber each other's
   rule runtime state). Verified live: 31/31 probes,
   `docs/perf/control-plane-pg-verify-2026-07-03.md`.
6. Helm wiring (`controlPlane.store=postgres` profile: env + secret, schema
   enum extension — the render gate then admits multi-replica) and cutover
   plan Phase 3 execution: kind staging at `replicaCount=2`, verifying
   exactly-one delivery per (webhook, event) with two pods, one alert page
   per incident, and a webhook registered through either pod visible to both.
   Chart wiring executed 2026-07-04: the `store` enum released to
   `[embedded, postgres]`, `controlPlane.postgres.{existingSecret,dsnKey}`
   sources the DSN, and `templates/deployment.yaml` wires
   `AGENTFLOW_CONTROLPLANE_STORE` + `AGENTFLOW_CONTROLPLANE_PG_DSN`; the scale
   profile is an overlay (`k8s/staging/values-staging-scale.yaml.example`), not
   a change to the zero-dependency default. Render side verified locally
   (`helm template`/`lint` + `tests/unit/test_helm_values_contract.py`), and
   re-verified 2026-07-06 on the Mac kind stand: the render gate correctly
   rejects `replicaCount=2` without both halves of the gate (the exact ADR
   error text) and correctly admits it once both are set (`replicas: 2`,
   correct env vars). The **two-real-pods live run** (kind at
   `replicaCount=2` + the replica-correctness checks above) needs Docker and
   was attempted 2026-07-06 on the Mac stand — genuinely incomplete: the
   shared host hit severe resource contention this session (co-tenant CPU
   spikes up to 80%, this cluster's own control plane crash-looping,
   `kube-apiserver` 10+ restarts) that stalled the `agentflow/api` image build
   itself at near-zero CPU progress across two attempts. See
   `docs/clickhouse-cutover-plan.md` Phase 3 for the full honest account.
   `scripts/k8s_replica_correctness_verify.sh` remains ready to automate the
   pod-count and cross-pod registration-visibility checks whenever the live
   run can complete; the delivery/alert checks follow the recipe in the
   cutover plan (their store-level guarantee is already live-verified by
   slice 5's 31/31 PG probes).

## Consequences

### Positive

- The scaling gate is enforced by the chart, not by a comment; it relaxes
  automatically and only when the store that makes scaling correct exists.
- One store, one adapter, one transaction model for all six state classes;
  the pinned regression suites transfer to the PG adapter unchanged.
- The demo/default profile keeps zero external dependencies and identical
  behavior through slices 1–4 (pure extraction).
- ADR 0007's "stateless pods" becomes literally true in the scale profile
  (no writable volume on the request path).

### Negative

- The scale profile requires an operator-provided PostgreSQL (DSN), a third
  stateful system next to ClickHouse and Redis.
- Per-pod event scanning is N× read amplification on the serving backend at
  scale (accepted; the scan is bounded and cheap, and consolidating scanners
  is a later topology refinement, cf. option 3).
- Until slice 6 extends the chart, multi-replica is simply impossible to
  render — a deliberate fail-closed period (the slice-5 adapter is app-side;
  the schema enum still pins `embedded` until the helm profile ships).

## Follow-up

- ADR 0009 remains accepted; its § Follow-up is resolved by this ADR.
- Cutover plan Phase 3 prerequisites updated to reference this rollout.
- The serving-read `_conn` seams noted out of scope here
  (`routers/lineage.py`, `routers/slo.py`) stay tracked via the 2026-07-02
  architecture audit (§3.6).
