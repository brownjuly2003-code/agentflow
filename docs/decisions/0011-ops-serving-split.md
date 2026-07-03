# ADR 0011: Operational serving split — transactional reads on the control-plane store, analytical reads on the serving backend

## Status

Accepted - 2026-07-03

Design decision for the operational layer (the three ops surfaces of
[`domain.md`](../domain.md) §4: **Order 360 timeline**, **stuck-orders
worklist**, **exception inbox**). The companion specification that pins
endpoint contracts, the SLA stage model, and per-slice scope is
[`docs/ops-surfaces-spec.md`](../ops-surfaces-spec.md); implementation is
staged as slices D2–D4 (see § Rollout).

## Context

The operations team of the modeled business juggles five tools to answer one
question about one order (`domain.md` §4). The serving layer exists to replace
that with one API surface, and the three planned ops surfaces are its most
read-shape-diverse consumers yet:

- **Order 360** is a *point-read composition*: one order row, its event
  history, its customer, its failures — "everything about ORD-20260404-1001,
  now, in one place".
- **Stuck-orders** is an *analytical scan*: every open order, joined to its
  stage-entry time, filtered against per-stage SLA budgets, ranked by
  overshoot.
- **Exception inbox** is a *transactional worklist*: failed events and
  consistency findings with a triage lifecycle (acknowledge / resolve /
  replay / dismiss) and a counter of absorbed manual work.

The platform has exactly two data planes, with different semantics, both
already behind ports:

| Plane | Port | Engines | Semantics |
|---|---|---|---|
| Serving / analytics | `ServingBackend` via `QueryEngine` (ADR 0006) | DuckDB (demo) / ClickHouse (scale) | Analytical reads: entity point-reads, metric aggregates, the `pipeline_events` journal scan (`QueryEngine.fetch_pipeline_events` — the freshness axis) |
| Control plane / transactional | `ControlPlaneStore` (ADR 0010) | embedded DuckDB+YAML (demo) / PostgreSQL (scale) | Mutable row state with claim semantics: webhook queue, alert state, outbox, **dead-letter lifecycle** (`failed → replay_pending → replayed` / `dismissed`), usage |

### Verified inventory — where each surface's data lives today (`main=c2749dd`)

| Data | Home | Access path | Notes |
|---|---|---|---|
| Order row, open-order set | `orders_v2` on the serving backend | `QueryEngine.get_entity` / catalog SQL | CH table is `ReplacingMergeTree ORDER BY order_id` — key point-reads are cheap on both engines |
| Per-order event history | `pipeline_events` journal | `QueryEngine.fetch_pipeline_events(entity_id=…)` | The journal has an `entity_id` axis, **but only the demo seed populates it** — the live pipeline writes journal rows without `entity_id` (`local_pipeline.py` insert sites, `clickhouse_sink.record_pipeline_event` has no such parameter). On CH the journal is `ORDER BY (tenant_id, topic, processed_at, event_id)`, so an `entity_id` lookup is scan-shaped — acceptable for one bounded order trail, wrong as a triage backbone |
| Customer golden record | `bv_customer_mdm` in the DV2 vault | engine-side governed views (ADR 0006 Phase 2) | PII-full, behind per-jurisdiction roles designed for warehouse principals. The serving store carries the PII-free projection `users_enriched` (the serving tier holds no PII by construction — 2026-07-01 decision) |
| Failed events + replay lifecycle | `dead_letter_events` + `outbox` | `ControlPlaneStore` | Tenant-scoped reads, `replay`/`dismiss` actions already live on `/v1/deadletter`; invariant 8 (outbox↔dead-letter transactional flip) preserved by the port |
| Webhook deliveries parked `dead` | webhook queue | `ControlPlaneStore` | Visible today only via per-webhook logs; no unified triage view |
| SLA budgets | nowhere yet | — | `contracts/entities/order.yaml` documents the status vocabulary but carries no stage budgets |
| OLTP hot tier (warehouse contour) | `ops_<branch>` PostgreSQL schemas (`pg_ops__*`) | DV2 promotion + LISTEN/NOTIFY | The warehouse-side archetype of the same split: "Postgres is a buffer, not a system of record; cross-branch joins live in CH, never in Postgres". Not wired to the serving API |

### Constraints

1. **The demo profile stays zero-dependency.** Both ports have embedded
   adapters; the ops surfaces must run on them unchanged.
2. **The serving tier stays PII-free by construction.** Whatever the timeline
   shows about a customer must come from the PII-free projection, not the
   vault.
3. **Freshness is the point.** These surfaces are the business reading of the
   event→metric axis (`domain.md` §4.1, oversell): a TTL-cached or
   batch-materialized ops read would re-create the very lag the five programs
   are being killed for.
4. **No third data path.** The 2026-07-02 architecture audit (§3.1, §3.6)
   spent an entire phase (E) evicting direct `query_engine._conn` reads from
   the control plane; the ops layer must not grow the seam back.

## Options considered

### 1. Serve everything from the analytics backend (ClickHouse at scale)

Rejected. Triage is mutable row state with lifecycle transitions and actions —
this re-litigates ADR 0010 option 1 (asynchronous mutations, no row locks,
no transactional flip). Worse, the dead-letter lifecycle *already* lives
behind the control-plane port; reading a CH copy of it would fork the state
the replay/dismiss actions mutate.

### 2. Serve everything from the transactional store (PostgreSQL at scale)

Rejected. The worklist and aging aggregates are analytical scans over serving
data; serving them from PG means copying `orders_v2` and the journal into the
control-plane store — a second serving engine, against ADR 0006. The
warehouse's own hot tier is explicitly a rolling 30-day buffer, not history.

### 3. Read the DV2 vault directly for the customer block

Rejected for v1. Vault PII sits behind per-jurisdiction engine-side roles
(officers, analysts) that were deliberately designed for warehouse
principals, not for an always-on API service account; and the timeline's
customer block needs no PII — `users_enriched` (orders, spend, recency,
preferred category) is exactly the PII-free projection of the golden record.
A dedicated non-PII vault role for a richer MDM block is recorded as roadmap,
not v1.

### 4. Precompute ops marts (materialized stuck-list / inbox tables)

Rejected for v1. The open-order set is small and bounded; computing on read
keeps the surfaces at serving-store freshness (constraint 3) and adds no new
moving parts. Materialization remains a later optimization that must not
change the API contract.

### 5. Two-port composition rule — chosen

Formalize the split the platform already converged on (ADR 0010: "ClickHouse
= analytics/serving, PostgreSQL = transactional state, Redis = cache/limits")
as a *rule for the ops layer*, executable today on the embedded profiles.

## Decision

1. **Every ops surface composes exactly the two existing ports.** Analytical
   reads — entity point-reads, journal scans and history, open-order
   aggregates — go through `QueryEngine` / `ServingBackend`. Transactional
   state — triage lifecycles, actions, the manual-work counter — goes through
   `ControlPlaneStore`. No ops code path touches `query_engine._conn`, a raw
   engine connection, or a vault DSN (spec invariant I1, pinned by a
   structural test like the slice-1 ratchet).

2. **Per-surface mapping:**

   | Surface | Serving backend (analytics) | Control-plane store (transactional) |
   |---|---|---|
   | Order 360 timeline | order row · stage history + pipeline trail from the journal · `users_enriched` customer block | dead-letter detail for the order's failed events (journal rows are the index, the store is the truth) |
   | Stuck-orders worklist | the whole computation (open orders × latest stage-entry row, budgets from the contract) | — |
   | Exception inbox | journal only as the entity index for findings | item truth: dead-letter lifecycle, dead webhook deliveries, reconciliation findings + triage overlay, stats/counter |

3. **The journal's entity axis becomes real.** The serving-store projection
   writes stage-entry rows (topic `orders.status`, event_type
   `order.status.<status>`, `entity_id` = order id) on every order status
   transition, and the existing validated/dead-letter journal writes carry
   `entity_id` where it is derivable from the event payload
   (`clickhouse_sink.record_pipeline_event` gains the parameter). Without
   this, the timeline and the stage clock exist only for seeded demo rows —
   the current live-write sites leave `entity_id` NULL.

4. **SLA budgets are catalog data, not code.** A `stages:` block in
   `contracts/entities/order.yaml` (ordered ladder, per-stage budget,
   terminal markers) is parsed into the catalog's `EntityDefinition` and is
   the only source of budgets for the worklist and the timeline's breach
   flag. Agents and SDKs see the SLA model through the same catalog surface
   as everything else.

5. **The exception-triage overlay is the seventh control-plane state class.**
   ADR 0010's inventory grows by one table (triage status for items that have
   no native lifecycle: dead webhook deliveries, reconciliation findings),
   implemented in both adapters. Items with a native lifecycle — dead-letter
   events — are *mapped* into the inbox read model and are never duplicated
   into the overlay; their actions stay on `/v1/deadletter`.

6. **Consistency semantics, stated:** ops surfaces read at serving-store
   freshness and are not metric-cached; the stage clock falls back to
   `created_at` (and says so) for orders with no stage rows; reconciliation
   checks run on inbox read with idempotent, dedupe-keyed finding upserts —
   safe at `replicaCount > 1` under ADR 0010's semantics (reads are
   stateless, writes are single-row transactions).

7. **Scale-profile evolution stays a swap, not a rewrite.** Rebinding the
   order point-read to a true OLTP hot tier (the `pg_ops__` pattern the
   warehouse contour already demonstrates) is a recorded F-phase option
   behind the same port boundary; the surface contracts in the spec must not
   change if that rebinding happens.

## Consequences

### Positive

- All three surfaces land on the zero-dependency demo profile — both ports
  already have embedded adapters, so D2–D4 add no services.
- The audit's "no third path" concern becomes an enforced rule (structural
  ratchet), not a review habit.
- Triage state inherits the PG adapter's transactional/claim semantics at
  scale for free; the pinned control-plane regression suites transfer.
- The SLA model is data (contract), so budget changes are a config edit with
  contract-versioning discipline, and the catalog/search surfaces expose it.

### Negative

- The stage clock depends on journal hygiene: orders written before the
  stage-row writer shipped (or by writers that bypass it) degrade to the
  `created_at` fallback — visible in the response (`clock: "fallback"`)
  rather than hidden.
- Seeding stage rows moves the demo `error_rate` denominator (it counts all
  journal rows in the window); the affected pinned tests are re-pinned by
  arithmetic, per the B3 house rule — recorded in the spec, not discovered in
  CI.
- The worklist is computed on read: O(open orders × journal window) per call.
  Bounded and cheap at demo scale; the materialization option is recorded for
  when it is not.
- Inbox reads trigger reconciliation checks against both stores — bounded
  read amplification, accepted for v1 (no scheduler dependency).

## Rollout

- **D2** — Order 360: timeline endpoint, journal entity axis (§ Decision 3),
  stage-entry seed trails, `error_rate` re-pins.
- **D3** — stuck-orders: `stages:` contract block + catalog parsing,
  `/v1/ops/stuck-orders`, aging/summary.
- **D4** — exception inbox: triage overlay (state class 7), sources
  (dead-letter mapping, dead webhook deliveries, reconciliation checks R1/R2),
  `/v1/ops/exceptions` + stats + manual-resolutions counter.

Each slice is one PR with the full suite green; endpoint contracts, schemas,
demo-story pins, and per-slice test obligations are in
[`docs/ops-surfaces-spec.md`](../ops-surfaces-spec.md).

## Follow-up

- F-phase option: order point-read rebinding to an OLTP hot tier behind the
  same port (Decision 7).
- Per-channel SLA budgets need a channel column on serving orders — recorded
  as out of v1 scope (`ops-surfaces-spec.md` § Non-goals).
- A non-PII vault role for a richer MDM customer block — roadmap (option 3).
- Container-ETA and marking-code exception sources (`domain.md` §4.2, §3) —
  named roadmap sources for the inbox, blocked on `excel__`/WMS feeds landing
  in the serving contour.
