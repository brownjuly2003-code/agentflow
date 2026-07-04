# Three-node demo topology - build contract (F2)

Concrete spec implementing [ADR 0012](decisions/0012-three-node-demo-topology.md).
This is the F2 target: what to build, how the nodes talk, and the machine-checkable
invariants (N1-N12) that are the test spec. Deploy of the Spaces is an owner gate.

Read ADR 0012 first for *why*; this doc is *how*. Terminology, roles, and the
honesty boundary are defined there and not repeated.

## 1. Space matrix

| Node   | Role     | Branch | Space                          | Live URL (planned)                          |
|--------|----------|--------|--------------------------------|---------------------------------------------|
| Center | `center` | `msk`  | `liovina/agentflow-center`     | `https://liovina-agentflow-center.hf.space` |
| Edge 1 | `edge`   | `spb`  | `liovina/agentflow-edge-spb`   | `https://liovina-agentflow-edge-spb.hf.space` |
| Edge 2 | `edge`   | `ekb`  | `liovina/agentflow-edge-ekb`   | `https://liovina-agentflow-edge-ekb.hf.space` |

All three build the **same image** (extend `deploy/hf-space/Dockerfile`, tracking
`main`). The existing `liovina/agentflow-demo` Space stays as-is (standalone role);
the three-node set is additive.

## 2. Environment matrix

One image; role is pure env. Public **variables** unless marked secret.

| Variable                     | Center                                  | Edge (spb / ekb)                         | Standalone (today) |
|------------------------------|-----------------------------------------|------------------------------------------|--------------------|
| `AGENTFLOW_NODE_ROLE`        | `center`                                | `edge`                                   | unset / `standalone` |
| `AGENTFLOW_NODE_BRANCH`      | `msk`                                   | `spb` / `ekb`                            | unset |
| `AGENTFLOW_NODE_CENTER_URL`  | -                                       | `https://liovina-agentflow-center.hf.space` | - |
| `AGENTFLOW_NODE_TOKEN`       | **secret** (accepts)                    | **secret** (sends; same value)           | - |
| `AGENTFLOW_DEMO_MODE`        | `true`                                  | `true`                                   | `true` |
| `AGENTFLOW_SEED_ON_BOOT`     | `true`                                  | `true`                                   | `true` |
| `DEMO_API_KEY`               | `demo-key`                              | `demo-key`                               | `demo-key` |

Rules:

- `AGENTFLOW_NODE_ROLE` unset or `standalone` => **no** node endpoint mounted, **no**
  emitter started - byte-identical to today's demo (N1).
- `AGENTFLOW_NODE_TOKEN` is the **same** string on all three; store as an HF Space
  **secret**, never a variable; never logged (N10).
- Center's `AGENTFLOW_NODE_CENTER_URL` is unused (center does not emit); edges
  require it, and boot must fail fast if an edge has role=`edge` but no center URL
  or no token.

## 3. Role dispatch (where the code hangs)

- Resolve role/branch once at startup in the `lifespan` (`src/serving/api/main.py`,
  alongside `app.state.demo_mode` at line 86). Store `app.state.node_role`,
  `app.state.node_branch`.
- **Center:** mount the ingest router (§4) only when role=`center`. Add its path to
  the demo-guard allow-list set next to `/v1/query` (main.py:291-294).
- **Edge:** start the emitter task (§6) in the `lifespan` only when role=`edge`.
- **Seed scoping (§5):** the boot seed (`initialize_demo_data`, main.py:123) takes
  the branch into account.
- Keep a single `src/serving/node/` module for role config + emitter + ingest
  handler so the node concern is one seam, not sprinkled through serving.

## 4. Ingest endpoint contract (center only)

```
POST /v1/node/events
Authorization: Bearer <AGENTFLOW_NODE_TOKEN>
Content-Type: application/json

{
  "origin_branch": "spb",
  "events": [ <canonical event>, ... ]   // 1..N, bounded (reject > 500)
}

200 OK  -> { "accepted": N, "applied": N, "dead_lettered": M }
401     -> missing/malformed bearer
403     -> wrong token, OR demo-key/public caller (demo-guard), OR role != center
422     -> body shape invalid (not the per-event schema - that dead-letters, see below)
```

- Auth: constant-time compare of the bearer against `AGENTFLOW_NODE_TOKEN`
  (reuse the pattern in `src/serving/api/auth/`); **not** the `demo-key` path.
- The demo-guard (`main.py:286-299`) blocks `POST` for the public key on every
  path except the allow-list; adding `/v1/node/events` to that set lets the
  **token-authenticated** node call through while the public `demo-key` still
  gets `403` (N3).
- Apply each event via `local_pipeline._process_event(conn, event, clickhouse_sink=...)`
  on the center's serving connection - **no new serving logic**. A per-event schema
  failure dead-letters exactly as in-process events do (that path already writes
  `events.deadletter` to `pipeline_events`); it does not fail the batch.
- Tag origin: set `event["source_metadata"]["branch"] = origin_branch` before
  applying, so the journal/lineage carry the branch (N4). Reject a batch whose
  `origin_branch` is not one of the known edge branches (N12).
- Idempotency: `_process_event` upserts orders by id and the journal is keyed by
  `event_id`; re-POSTing the same batch must not double-count (N5).

## 5. Canonical event payload

The `events[]` items are exactly what the producers already emit - do not invent a
new schema. Produced by `generate_order|generate_payment|generate_click|generate_product`
(`src/ingestion/producers/event_producer.py`) via `json.loads(model.model_dump_json())`; see
`local_pipeline._generate_random_event`. Shape (illustrative order event):

```json
{
  "event_id": "evt-...",
  "event_type": "order.created",
  "tenant": "default",
  "order_id": "ORD-20260404-...",
  "source_metadata": { "tenant": "default", "branch": "spb" },
  "...": "producer payload fields"
}
```

Keys the pipeline reads: `event_type` (prefix routes upsert: `order.`/`payment.`/
`product.`/`session.`), `event_id` (journal key), `tenant` or
`source_metadata.tenant`, and the entity-id field per prefix (`order_id`/`user_id`/
`product_id`/`session_id`, `_derive_entity_id`). `validate_event` gates admission.

## 6. Edge emitter (edge only)

Reuse, do not rebuild:

- The edge already can run `local_pipeline.run()` (the background generator). In
  edge role, run a **slow** generator loop (e.g. 1 event / few seconds - low, this
  is a demo not a load test) that for each produced `(topic, event)`:
  1. applies it locally via `_process_event` (edge's own read surface stays live), then
  2. **forwards the same dict** to `POST {AGENTFLOW_NODE_CENTER_URL}/v1/node/events`
     with the node token, batching a few events per request.
- Local apply and forwarded payload are the **same** canonical dict (N7).
- Cold-center tolerance (N9): short timeout (~3-5 s), 2-3 retries with backoff; on
  give-up, drop + log at info, **never** raise into the loop (the edge must stay up
  and its own page must stay live even if the center is down/sleeping).
- The emitter only runs while the edge Space is awake; that is the intended sleep
  behavior, not a bug (§8).

## 7. Seeding and branch scoping (§ ADR 0012 Decision 4)

- Edge boot seeds **its branch slice**: `initialize_demo_data` scoped/filtered by
  `AGENTFLOW_NODE_BRANCH` (store/branch column in the demo tables per `domain.md`
  §5.2 `store_code` `msk-01`/`spb-shr-02`/...). If the current seed is not yet
  branch-parameterizable, the minimal change is a post-seed filter by branch; keep
  it a pure function of the branch so restarts are deterministic (N11).
- Center boot seeds the **catalog + an aggregate baseline across all three
  branches**, so a center-first visitor sees a coherent cross-branch picture
  before any live event (N8 baseline half).

## 8. Sequences

**Boot (any node):** container start -> `lifespan` resolves role/branch -> seed
(branch slice for edge, all-branch baseline for center) -> demo guards on ->
(center) ingest mounted / (edge) emitter task started.

**Live emit (happy path):** visitor opens edge `spb` -> edge awake -> generator
produces `order.created` -> applied locally (spb read surface updates) -> forwarded
to center -> center `_process_event` -> center cross-branch metric for `spb` moves;
Order 360 timeline / lineage carry `branch=spb`.

**Sleep + wake:** center asleep, edge awake and emits -> first POST wakes the center
(cold start seconds) -> that POST may time out -> emitter retries -> center up, seeds
baseline, applies the retried batch. Center-first visitor while both edges sleep ->
sees baseline + "no live events yet" per branch (N8); UI copy: "open a branch Space
to see its events flow to the hub."

**Restart (ephemerality):** any node restart -> disk gone -> re-seed baseline ->
live layer reset to zero. Deterministic baseline (N11); README states the live layer
resets on hub restart.

## 9. Cross-branch view + graceful degradation

- Center exposes a cross-branch summary (extend the existing admin/UI surface or a
  read endpoint composing per-branch counts from the journal - reuse
  `QueryEngine`/serving reads, no new store). Per branch: baseline figure, live
  delta this lifecycle, and **last-seen** timestamp (null => "waking / no live
  events yet"). Never error on a silent branch (N8).

## 10. Optional: center-initiated wake-poke (record, do not default)

A center visitor could trigger a best-effort GET to each edge's `/v1/health` to wake
them, so cross-branch liveness appears without the visitor opening each edge. This
reintroduces a pull and its sleep-timeout handling; keep it **optional/off by
default** behind a flag - the core design is push-only (ADR 0012 Decision 5).

## 11. Deploy runbook skeleton (owner gate)

The concrete runbook and per-role Space READMEs live in
`deploy/hf-space/three-node/` (`DEPLOY.md` + `center/`, `edge-spb/`, `edge-ekb/`
READMEs; the shared image is the existing `deploy/hf-space/Dockerfile`).
`HF_TOKEN` from `D:/VacancyRadar/.env` - never printed. For each of
`agentflow-center`, `agentflow-edge-spb`, `agentflow-edge-ekb`:

```bash
# 1. Create (one-time)
huggingface-cli repo create <name> --repo-type space --space_sdk docker
# 2. Push Dockerfile + README.md (per-role frontmatter/title) to the Space repo root
# 3. Set env in the Space Settings:
#    - variables: AGENTFLOW_NODE_ROLE / _BRANCH / _CENTER_URL (edges) / DEMO_MODE / SEED_ON_BOOT
#    - secret:    AGENTFLOW_NODE_TOKEN  (same value on all three)
```

Bring-up order: **center first** (edges need its URL live), then the two edges.

## 12. Verify-live checklist (F2 done-gate)

- `curl {center}/v1/health`, `{edge-spb}/v1/health`, `{edge-ekb}/v1/health` -> all 200.
- Public demo-key `POST {center}/v1/node/events` -> `403` (demo-guard holds, N3).
- `POST {center}/v1/node/events` with the node token, one seeded `spb` order ->
  `200 applied:1`; then a center cross-branch read shows `spb` last-seen set and the
  metric moved (N4).
- Re-POST the same batch -> center count unchanged (N5).
- Open edge `spb`, wait, open center -> `spb` shows a non-zero live delta (end-to-end).
- Center-first while edges idle -> baseline + "no live events yet", no error (N8).

## 13. Node invariants (test spec - N1-N12)

Machine-checkable; each is a unit/integration test F2 must add (mirrors
`ops-surfaces-spec.md` I1-I12).

- **N1** Standalone role (no `AGENTFLOW_NODE_ROLE`): `/v1/node/events` is not mounted
  (`404`), no emitter task; behavior byte-identical to today's demo.
- **N2** `/v1/node/events` mounted iff role=`center`; edge/standalone => `404`.
- **N3** Ingest rejects the public `demo-key` (`403`, demo-guard) and missing/wrong
  bearer (`401`/`403`); accepts the correct `AGENTFLOW_NODE_TOKEN`.
- **N4** A valid POSTed event is applied via `_process_event`, lands in
  `pipeline_events` tagged `branch=<origin>`, and moves the matching center metric.
- **N5** Idempotency: the same `event_id` POSTed twice does not double-count.
- **N6** Edge boot seeds only its `AGENTFLOW_NODE_BRANCH` slice; center seeds the
  all-branch baseline.
- **N7** Edge emitter applies locally and forwards the **same** canonical dict.
- **N8** Center cross-branch view: a branch with zero live events shows baseline +
  null last-seen + "waking" state, never an error.
- **N9** Emitter tolerates a cold/unreachable center: bounded timeout+retries, drops
  on give-up, never raises into the generator loop.
- **N10** Node token: constant-time compare, sourced from env/secret, never logged.
- **N11** Restart determinism: re-seed after restart yields the same baseline (pure
  function of branch + pinned dataset).
- **N12** Role/branch guard: ingest refused in non-center role even with a valid
  token; batch with an unknown/mismatched `origin_branch` rejected.

## 14. F2 implementation order (small PRs, full suite green each)

1. `src/serving/node/` config resolution (role/branch/center-url/token) + fail-fast
   boot validation + N1/N2 tests. No behavior change for standalone.
2. Center ingest endpoint (`POST /v1/node/events`) + demo-guard allow-list + auth +
   `_process_event` wiring + branch tag + N3/N4/N5/N12 tests.
3. Edge emitter task (reuse generator; local-apply + forward; cold-center tolerance)
   + N7/N9 tests.
4. Branch-scoped seed (edge slice / center baseline) + N6/N11 tests.
5. Center cross-branch view + graceful degradation + last-seen + N8 test.
6. Per-role Dockerfile/README frontmatter + deploy runbook doc; **deploy = owner
   gate**; then verify-live (§12).

Steps 1-5 are autonomous (no Docker, unit/integration-testable on the existing
single-container path with a mocked peer). Step 6's deploy is the external gate.
