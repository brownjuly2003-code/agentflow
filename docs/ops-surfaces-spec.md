# Ops Surfaces Spec — Order 360, Stuck-Orders, Exception Inbox

The implementation contract for the operational layer: the three surfaces
that replace the five-tool triage routine described in
[`domain.md`](domain.md) §4. The architectural decision they execute — which
data plane serves which read shape — is
[ADR 0011](decisions/0011-ops-serving-split.md); this document pins the
endpoint contracts, the SLA stage model, the exception sources, the demo
story, and the per-slice test obligations.

Consumers:

- **D2** — Order 360 timeline (§2, plus the shared foundations §1.2–§1.4 and
  §1.6 it delivers).
- **D3** — stuck-orders worklist (§3, plus the contract `stages:` block
  §1.5).
- **D4** — exception inbox (§4).
- §5 is the invariant list — the test ТЗ for all three slices, in the same
  spirit as `generator-spec.md` §12.

Ground rules inherited from ADR 0011: every surface composes exactly the
`QueryEngine`/`ServingBackend` port (analytical reads) and the
`ControlPlaneStore` port (transactional state); no `_conn`, no vault DSN; the
demo profile runs everything on the embedded adapters with zero new
dependencies.

## 1. Shared foundations

### 1.1 Stage model

Stages are the business fulfilment statuses already pinned by
`contracts/entities/order.yaml`:

```
pending → confirmed → shipped → delivered
                    ↘ cancelled (from any non-terminal stage)
```

- **Ladder (non-terminal, in flow order):** `pending`, `confirmed`,
  `shipped`.
- **Terminal:** `delivered`, `cancelled` — never stuck, never carry a budget.
- Stages are distinct from the *pipeline trail* (`order.created`,
  `order.validated`, `order.served`, dead-letter/replay events): the trail
  describes the platform moving data, stages describe the warehouse moving
  goods. The timeline shows both, separately (§2.2).

### 1.2 Stage-entry journal rows

The `pipeline_events` journal is the stage clock. A stage entry is one
journal row:

| Column | Value |
|---|---|
| `topic` | `orders.status` |
| `event_type` | `order.status.<status>` (e.g. `order.status.confirmed`) |
| `entity_id` | the order id (`ORD-…`) |
| `tenant_id` | tenant of the write, as elsewhere in the journal |
| `processed_at` | the transition time |
| `latency_ms` | `NULL` (not a pipeline hop) |

Writer: the serving-store projection site — wherever `orders_v2` is created
or its `status` transitions (local pipeline write path and its ClickHouse
mirror), one `orders.status` row is emitted alongside. Order creation emits
`order.status.pending`. The event-type namespace `order.status.*` is
deliberately disjoint from the ingestion vocabulary (`order.created`,
`order.updated`, …) so nothing that filters on ingestion types picks up
stage rows.

### 1.3 Journal entity axis on live writes

Today only the demo seed populates `pipeline_events.entity_id`; the live
write sites leave it NULL (`local_pipeline.py` validated/dead-letter inserts
name six columns without `entity_id`; `clickhouse_sink.record_pipeline_event`
has no such parameter). D2 fixes both:

- validated and dead-letter journal writes carry `entity_id` extracted from
  the event payload when derivable (`order_id` for `order.*` events,
  `user_id` for `user.*`, `product_id` for `product.*`, `session_id` for
  `session.*`); NULL when not derivable — never a synthesized id;
- `clickhouse_sink.record_pipeline_event` gains an `entity_id: str | None`
  keyword (default `None` — existing callers stay valid).

### 1.4 Stage clock resolution

For an order whose current status is `S` (from `orders_v2`):

1. `entered_at` = max `processed_at` over journal rows with
   `topic='orders.status'`, `entity_id=<order>`, `event_type='order.status.S'`;
   `clock: "journal"`.
2. No such row → `entered_at = created_at` (the order row), `clock:
   "fallback"`. Honest degradation for pre-existing or bypass-written orders;
   the response says so rather than hiding it.
3. `in_stage_seconds = now − entered_at`; `breached = in_stage_seconds >
   sla_minutes × 60` for ladder stages, `null` for terminal or unknown
   stages.
4. A status outside the contract vocabulary resolves to `stage: unknown`,
   `breached: null` — surfaced, never a crash (I4).

### 1.5 SLA budgets — the `stages:` contract block

Budgets are catalog data. `contracts/entities/order.yaml` gains:

```yaml
stages:
  - name: pending
    sla_minutes: 30
    description: Confirmation SLA — marketplace orders auto-confirm within
      minutes; a pending order older than this needs a payment/CRM decision
  - name: confirmed
    sla_minutes: 1440
    description: Ship-by SLA — FBS marketplace shipping deadlines drive the
      24h budget for warehouse handover
  - name: shipped
    sla_minutes: 7200
    description: Delivery SLA — 5 days courier/pickup before a customer
      contact is due
  - name: delivered
    terminal: true
  - name: cancelled
    terminal: true
```

- List order = ladder order. `terminal: true` entries carry no
  `sla_minutes`.
- Parsed into an optional `stages` field on the catalog's
  `EntityDefinition` (default `None` — entities without the block behave as
  today; catalog parsing must not require it).
- The block is the **only** source of budgets (I2): no stage literals or
  budget constants in router/engine code.
- One ladder for all channels in v1. Per-channel budgets (B2B wholesale
  vs FBS have genuinely different clocks) require a channel column on
  serving orders — recorded in § Non-goals.
- Budget values above are grounded in the legend (`domain.md` §2): they are
  the demo defaults, and changing them is a contract edit, not a code edit.

### 1.6 Demo story (seed additions and their pinned consequences)

D2 seeds stage trails for the 8 demo orders (both backends, mirrored — the
B3 discipline): each order gets `order.status.pending` at its `created_at`,
plus stage entries consistent with its current status, back-dated
plausibly between `created_at` and now. Pinned outcomes:

- **ORD-20260404-1004** (pending, created 45 min ago) is the sole SLA breach
  in the demo — 45 min in `pending` against a 30-min budget, overshoot 1.5×.
  The stuck-orders default view returns exactly this order (I7). The
  legend reading: a marketplace order stuck before confirmation — the "где
  заказ?" question the ops manager asks first.
- **ORD-20260404-1001** (delivered) shows the full Order 360 story: complete
  stage history, the existing pipeline trail (`order.created` →
  `order.validated` → `order.served`), and the customer block for
  `USR-10001` (I7).
- Every other open order sits inside its budget; terminal orders
  (`delivered`/`cancelled`) never appear in the worklist.

Seeding stage rows grows the journal, and the demo `error_rate` divides
dead-letter rows by **all** journal rows in the window — the pinned demo
value moves. Re-pin expected values by arithmetic from the new seed
(house rule since B3), never by copying observed output (I9).

### 1.7 Tenancy and auth

- All three surfaces resolve the tenant from request state exactly like the
  existing entity/deadletter routes, and scope both ports' reads with it
  (I8).
- Reads require a valid API key (any scope). Mutations (inbox
  acknowledge/resolve) follow the dead-letter write rule: full-access keys
  only; scoped keys get 403.

### 1.8 Caching

Ops responses are not metric-cached and set no cache headers: they are the
"now" surface (ADR 0011 constraint 3). The underlying entity/journal reads
are already cheap on both engines at the volumes involved.

## 2. Surface 1 — Order 360 timeline (D2)

**`GET /v1/entity/order/{order_id}/timeline`** — same router family as the
existing entity read (`agent_query.py` owns `/v1/entity/*`), same 404
semantics (unknown order → 404, same shape as the entity route), same tenant
scoping.

### 2.1 Composition (per ADR 0011 mapping)

| Block | Source port | Read |
|---|---|---|
| `order` | serving | `QueryEngine.get_entity("order", id)` |
| `stage` + `stage_history` | serving | journal rows `topic='orders.status'`, `entity_id=<id>`, ascending; clock per §1.4 |
| `pipeline_trail` | serving | journal rows for `entity_id=<id>` with `topic != 'orders.status'`, ascending |
| `customer` | serving | `QueryEngine.get_entity("user", order.user_id)` — the PII-free serving projection of the MDM golden record (`users_enriched`); `null` when absent |
| `exceptions` | control plane | for trail rows with `topic='events.deadletter'`: `get_dead_letter_event(event_id, tenant)` — the journal is the index, the store is the truth |

### 2.2 Response shape

```json
{
  "order": { "order_id": "…", "user_id": "…", "status": "…",
             "total_amount": 0, "currency": "RUB", "created_at": "…" },
  "stage": { "current": "pending", "entered_at": "…",
             "in_stage_seconds": 2700, "sla_minutes": 30,
             "breached": true, "clock": "journal" },
  "stage_history": [ { "status": "pending", "at": "…" } ],
  "pipeline_trail": [ { "event_id": "…", "topic": "…", "event_type": "…",
                        "latency_ms": 12, "processed_at": "…" } ],
  "customer": { "user_id": "…", "total_orders": 34, "total_spent": 0,
                "first_order_at": "…", "last_order_at": "…",
                "preferred_category": "grills" },
  "exceptions": [ { "event_id": "…", "failure_reason": "…", "status": "failed",
                    "occurred_at": "…",
                    "actions": { "replay": "/v1/deadletter/{id}/replay",
                                 "dismiss": "/v1/deadletter/{id}/dismiss" } } ]
}
```

The customer block is a fixed field allow-list (the `users_enriched`
columns) — no PII field can appear in a timeline response by construction
(I3).

### 2.3 D2 scope

Endpoint + response models; §1.2 stage-row writer (both write paths); §1.3
entity axis on live writes; §1.6 seed trails; `error_rate`/journal-count
re-pins by arithmetic; tests per §5.

## 3. Surface 2 — stuck-orders worklist (D3)

**`GET /v1/ops/stuck-orders`** — new `routers/ops.py` (prefix `/v1/ops`).

### 3.1 Parameters

| Param | Default | Meaning |
|---|---|---|
| `stage` | — | filter to one ladder stage |
| `include_within_sla` | `false` | `true` returns the whole open worklist, not only breaches |
| `page` / `page_size` | `1` / `50` (max 100) | dead-letter pagination conventions |

### 3.2 Computation

One serving-backend query shape (no per-order round-trips): open orders
(`status` in the ladder) left-joined to their latest `orders.status` row,
`entered_at` fallback per §1.4, budgets from the contract `stages:` block
(I2), `overshoot_ratio = in_stage_seconds / (sla_minutes × 60)`. Default
view: breaches only, ordered by `overshoot_ratio` desc. Computed on read at
serving-store freshness — no materialized state (ADR 0011 option 4).

### 3.3 Response shape

```json
{
  "items": [ { "order_id": "…", "user_id": "…", "status": "pending",
               "entered_at": "…", "in_stage_seconds": 2700,
               "sla_minutes": 30, "overshoot_ratio": 1.5,
               "clock": "journal", "total_amount": 1890.0,
               "currency": "RUB" } ],
  "summary": { "open_by_stage": { "pending": 2, "confirmed": 2, "shipped": 1 },
               "breached_by_stage": { "pending": 1 } },
  "pagination": { "page": 1, "page_size": 50, "total": 1, "pages": 1 }
}
```

### 3.4 D3 scope

Contract `stages:` block + catalog parsing (§1.5, optional field, tolerant
of absence); endpoint + summary; tests per §5. D3 depends on D2's stage rows
being seeded/written but degrades honestly without them (`clock:
"fallback"` from `created_at` — the demo breach story survives either way,
since ORD-1004's pending entry equals its `created_at`).

## 4. Surface 3 — exception inbox (D4)

**`GET /v1/ops/exceptions`** · **`GET /v1/ops/exceptions/stats`** ·
**`POST /v1/ops/exceptions/{item_id}/acknowledge`** ·
**`POST /v1/ops/exceptions/{item_id}/resolve`**

One triage feed for "what failed and needs a human" (`domain.md` §4.3),
aggregating sources that today live on three different screens.

### 4.1 Sources (v1)

| # | Source | Truth | Lifecycle | Actions |
|---|---|---|---|---|
| 1 | Dead-letter events | `ControlPlaneStore` dead-letter methods (tenant-scoped) | **native**, mapped read-only: `failed → open`, `replay_pending → in_progress`, `replayed`/`dismissed → resolved` | links to `/v1/deadletter/{id}/replay` and `/dismiss`; inbox mutation of a `dl:` item → 409 (I6) |
| 2 | Webhook deliveries parked `dead` | webhook queue via a new port read (`list_dead_webhook_deliveries`, both adapters) | overlay (§4.2) | `acknowledge` / `resolve` |
| 3 | Reconciliation findings (§4.3) | computed on read, upserted into the overlay by dedupe key | overlay, plus **auto-resolve** when a finding no longer reproduces | `acknowledge` / `resolve` |

Roadmap sources, named but not v1: container-ETA staleness (`excel__`
manifests), marking-code gaps at receiving (`domain.md` §3), SLO freshness
breaches (already alertable via `/v1/slo` + alert rules — the inbox links
rather than duplicates alerting).

### 4.2 Triage overlay — control-plane state class 7

One table (embedded DuckDB + PostgreSQL adapters, extending ADR 0010's
inventory):

```
ops_exception_triage(
  item_id      TEXT PRIMARY KEY,   -- stable id, §4.4
  tenant_id    TEXT,
  source       TEXT,               -- 'webhook_delivery' | 'reconciliation'
  status       TEXT,               -- 'open' | 'acknowledged' | 'resolved'
  first_seen_at / last_seen_at / resolved_at TIMESTAMP,
  note         TEXT                -- optional operator note on resolve
)
```

Port methods (names final at implementation, semantics pinned here):
ensure-schema; get/list triage states for a set of item ids; set state
(single-row transactional upsert); upsert-finding (insert `open` or refresh
`last_seen_at`; **never** reopens a row an operator resolved unless the
finding reproduces after `resolved_at`); count manual resolutions for the
stats window. Dead-letter items get **no** overlay rows — their native
machine is the single source of truth (I6).

### 4.3 Reconciliation checks (v1)

Concretizing the "reconciliation" half of the phase-D plan — cross-store
consistency probes that today are nobody's job:

- **R1 `journal_vs_store`** (severity `high`): over the check window, for
  every `entity_id` seen in `orders.status` journal rows, the serving store
  must have the order row and its `status` must not be *behind* the latest
  journal stage. A mismatch means an event landed but the serving projection
  didn't (or forked) — the silent failure mode of the store-and-journal
  double write. Dedupe key: `r1:<order_id>:<expected_status>`.
- **R2 `stuck_replay`** (severity `medium`): dead-letter rows sitting in
  `replay_pending` longer than a threshold (default: the control-plane lease
  interval; env-tunable) — a replay was requested but its outbox entry never
  completed the invariant-8 flip. Dedupe key: `r2:<event_id>`.

Checks run on inbox read (no scheduler dependency), read both ports
read-only, and write only overlay upserts — idempotent and dedupe-keyed, so
concurrent reads and `replicaCount > 1` are safe (I10). A finding absent in
the current run auto-resolves its `open` overlay row (status `resolved`,
note `auto-resolved: no longer reproduces`).

### 4.4 Item model

```json
{ "item_id": "dl:evt-004",
  "source": "deadletter" | "webhook_delivery" | "reconciliation",
  "severity": "high" | "medium" | "low",
  "occurred_at": "…", "last_seen_at": "…",
  "entity_ref": { "kind": "event" | "order" | "webhook", "id": "…" },
  "title": "…", "detail": "…",
  "status": "open" | "in_progress" | "acknowledged" | "resolved",
  "actions": [ … ] }
```

Stable ids: `dl:<event_id>`, `wh:<webhook_id>:<event_id>`,
`rc:<dedupe_key>` — the same underlying fact always maps to the same
`item_id` (I5). List params: `source`, `status` (default: everything not
`resolved`), pagination as §3.1. Severity defaults: dead-letter `high`,
dead webhook delivery `medium`, per-check for reconciliation.

### 4.5 Stats and the manual-work counter

`GET /v1/ops/exceptions/stats` returns counts by `source × status`, a
`last_24h` new-item count, and **`manual_resolutions`** for the window: the
number of human triage decisions absorbed by the platform — dead-letter
replays + dismisses (from native state transitions) + overlay
acknowledge/resolve actions. This is the kill-five-programs KPI
(`domain.md` §4): triage decisions that used to be five-screen detective
work, countable because they now happen in one feed.

### 4.6 D4 scope

Overlay table + port methods in both adapters; `list_dead_webhook_deliveries`
port read; R1/R2 checks; the three endpoints; a non-empty demo inbox story —
the two seeded dead-letter journal rows (`evt-004`, `evt-009`) get store
counterparts so the demo feed shows real items (affected dead-letter
stats/count pins re-pinned by arithmetic, I9); tests per §5.

## 5. Invariants (the test ТЗ)

Machine-checkable; each Dx slice lands the tests for the invariants it
touches, and G2 audits against the full list.

- **I1 — no third path (structural ratchet).** No module under
  `routers/ops*` and no timeline code references `query_engine._conn`, a raw
  backend connection, or a vault DSN; ops surfaces import only the two
  ports. Same test pattern as the ADR 0010 slice-1 dispatcher ratchet.
- **I2 — budgets only from the contract.** No stage-name or budget literal
  in ops router/engine code paths; pointing the catalog at a fixture
  contract with different `sla_minutes` changes worklist/timeline behavior
  accordingly.
- **I3 — PII-free by construction.** Timeline and inbox response models are
  fixed allow-lists; `first_name`/`last_name`/`email`/`phone`/`birth_date`
  never appear (structural test over the response models, not a runtime
  scrub).
- **I4 — stage vocabulary tolerance.** Stage rows use `topic='orders.status'`
  and `event_type='order.status.<status>'`; a status outside the contract
  ladder yields `stage: unknown` / `breached: null`, never a 500.
- **I5 — stable item ids.** Same fact → same `item_id` across calls;
  listings never show duplicates for one underlying fact.
- **I6 — native lifecycles are not duplicated.** `dl:` items have no overlay
  rows; inbox mutation endpoints reject them with 409; their status in the
  feed always mirrors the dead-letter store.
- **I7 — demo story pins.** Default worklist = exactly `ORD-20260404-1004`
  (overshoot 1.5×, clock `journal`); `ORD-20260404-1001` timeline carries a
  ≥3-row pipeline trail, full stage history, and the `USR-10001` customer
  block; the demo inbox is non-empty.
- **I8 — tenant scoping.** Every surface scopes both ports' reads by the
  request tenant; a foreign tenant's key sees none of the demo tenant's
  orders/items (cross-tenant test per surface).
- **I9 — re-pin by arithmetic.** Seed changes (stage rows, dead-letter store
  counterparts) re-pin affected expected values (`error_rate`, dead-letter
  stats) computed from the seed, never copied from observed output.
- **I10 — read surfaces don't write serving state.** Ops endpoints perform
  no serving-store writes; reconciliation writes only overlay upserts;
  running checks concurrently is idempotent (dedupe keys).
- **I11 — live journal writes carry the entity axis.** Validated and
  dead-letter journal writes (DuckDB path and ClickHouse mirror) set
  `entity_id` for payloads where it is derivable; unit tests cover both
  sites.
- **I12 — fallback honesty.** An order with no stage rows reports
  `clock: "fallback"` with `entered_at = created_at` — asserted, so the
  degraded mode stays visible instead of silently pretending to be a
  journal clock.

## 6. Non-goals (v1)

- **Per-channel SLA ladders** — needs a channel column on serving orders;
  single ladder v1 (§1.5).
- **Container-ETA / marking-code exception sources** — blocked on
  `excel__`/WMS feeds reaching the serving contour (`domain.md` §4.2);
  named roadmap in §4.1.
- **Vault MDM block in the timeline** — needs a dedicated non-PII vault
  role (ADR 0011 option 3); `users_enriched` projection v1.
- **Materialized ops marts** — computed-on-read v1 (ADR 0011 option 4); the
  API contract must survive later materialization unchanged.
- **Push notifications for breaches** — the alert subsystem already owns
  paging; the inbox links to it rather than growing a second notifier.
- **A generic workflow engine** — the overlay is triage state (three
  statuses, one note), not case management.
