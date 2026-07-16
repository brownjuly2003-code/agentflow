# Changelog

All notable changes to AgentFlow are documented in this file.

## [Unreleased]

### Helm — ServiceAccount is a pre-hook before the provision Job

- **First `helm install` with ClickHouse provisioning no longer hangs** waiting
  for SA `agentflow`. The chart `ServiceAccount` is a `pre-install,pre-upgrade`
  hook (weight `-10`) so it exists before the provision Job (weight `-5`).
  Root-caused on the E4 kind stand (`docs/perf/e4-check3-exactly-one-delivery-2026-07-16.md`).

### K8s — replica-correctness Check 4 (alert single-page) automated

- **`scripts/k8s_replica_correctness_verify.sh` Check 4** creates a firing alert
  rule and asserts exactly one successful `alert.triggered` history row across
  two pods (`claim_alert_tick` single-flight). Closes the remaining Phase 3
  recipe item at the automation layer; live evidence still needs a scale-stand
  re-run.

### Supply chain — Gate 2: Dependabot security updates + required-check gap closed

- **Dependabot security updates enabled** on the repo (vulnerability alerts +
  automated security fixes). Advisories open a PR immediately; weekly
  version updates in `.github/dependabot.yml` stay for ordinary bumps.
- **Branch protection required checks: 13 → 15** — added `sdk-ts` and
  `lock-check` so the TypeScript SDK CI job and the `uv.lock` /
  `requirements-docker.lock` gate cannot be skipped on `main`.
- Living docs (`README`, `docs/release-readiness.md`) and the dependabot
  header comment updated to match the API-verified state.

### Observability — /v1/slo reports SLIs, not rescaled aggregates (audit P2-2)

- **`current` is now a real SLI**: the share of good units among valid units
  over the SLO window. Latency: events at or under the threshold (the p95
  moves to `diagnostic` — a p95 of 2x the threshold says nothing about how
  MANY requests were slow). Errors: non-5xx (or non-dead-letter) share.
  Freshness: time-weighted — the share of observed seconds during which the
  newest journal row was at most threshold old, reconstructed exactly from
  event gaps (`min(gap, threshold)` per gap plus the tail). The old
  `threshold / measured` rescale is gone.
- **Missing data is `unknown`, not 0.0** — `current`,
  `error_budget_remaining` go null and `status` says `"unknown"`: an empty
  journal is missing data, not a missed target.
- **Multi-window burn rates** (`burn_rates: {1h, 6h, 3d}`,
  `(1 - sli) / (1 - target)`): the (1h, 6h) pair over 14.4 or the (6h, 3d)
  pair over 6 marks the SLO `at_risk` even while the full window still looks
  healthy — a month of clean traffic no longer hides an hour burning budget
  at 25x. The response also carries `good`/`valid`/`unit`, so every number
  is auditable from the payload.
- Live-verified on ClickHouse 25.3, where the freshness SQL's
  `LAG(...) OVER` transpiles to `lagInFrame` — which hands the FIRST row a
  zero-date instead of NULL and, without the epoch guard now in place,
  booked a phantom threshold-sized credit. Pinned by a live probe with
  exact numbers.

### Scale — search maintenance reads the journal, not the world (audit P1-6)

- **The periodic tick is a `refresh()`, not a rebuild.** It reads
  `pipeline_events` past a cursor: a quiet journal costs one bounded read and
  zero table scans; a small change-set costs targeted `IN` re-reads of
  exactly the rows the journal named (`scan_entity_rows_by_ids`, through the
  active backend), upserted copy-on-write so a concurrent search never sees a
  half-applied batch. Document frequencies are maintained incrementally, and
  the result is pinned byte-equivalent to a full rebuild.
- **The full pass survives where it is honest**: on a cold cursor, when the
  journal window overflows (completeness would be a guess), when the
  change-set outgrows targeted reads, and unconditionally every
  `AGENTFLOW_SEARCH_FULL_REBUILD_TICKS` ticks — the bounded-staleness safety
  net for journal-bypassing writers and deletions. Knobs:
  `AGENTFLOW_SEARCH_REFRESH_WINDOW` (default 1000),
  `AGENTFLOW_SEARCH_CHANGED_IDS_LIMIT` (512),
  `AGENTFLOW_SEARCH_FULL_REBUILD_TICKS` (10).
- **Measured, not asserted**: the scale probe shows a 10-row refresh over a
  3000-row corpus allocating under a fifth of a rebuild's peak with zero
  wholesale scans, and the live ClickHouse suite proves a post-boot row is
  picked up incrementally and stays visible to its own tenant only.

### Scale — the PostgreSQL control plane grows up (audit P1-1)

- **Bounded connection pool.** `PostgresControlPlaneStore` checks connections
  out of a `psycopg_pool.ConnectionPool` (min/max/timeout via
  `AGENTFLOW_CONTROLPLANE_PG_POOL_*`, default 1/10/10s) instead of
  `psycopg.connect()` per method call — the per-process PostgreSQL footprint
  is now a budget, not a function of request rate. Transaction semantics are
  unchanged (checkout = one transaction, commit/rollback on exit). Pool
  pressure is scrapeable (`agentflow_pg_pool_connections{state}`,
  `agentflow_pg_pool_requests_waiting`, `agentflow_pg_pool_max_size`) and
  alertable (`ControlPlanePoolSaturated`, `UsageRowsDropped` in
  `monitoring/alerting/rules.yml`). The `postgres` extra becomes
  `psycopg[binary,pool]`; the store closes its pool on lifespan shutdown.
- **`record_api_usage_batch` is one transaction.** The base-class fallback
  paid a connection and a commit per row — a 256-row batch could open 256
  connections. Now: one checkout, one `executemany`, one transaction; the
  live probe proves every row of a 256-row batch shares one `xmin`.
- **Versioned migrations.** Schema DDL moved from a flat
  `CREATE TABLE IF NOT EXISTS` pile to a monotonic `_MIGRATIONS` ledger
  recorded in `control_plane_schema_version`; concurrent replicas serialize
  on a transaction-scoped advisory lock (live probe: four replicas race a
  fresh database, one applies, ledger stays single). A pre-versioning
  database upgrades in place: migration 1 is the baseline, pure
  `IF NOT EXISTS`, and gets stamped without touching data.
- **Process roles.** `AGENTFLOW_PROCESS_ROLE=api` serves requests and runs
  no delivery loops (webhook/alert dispatchers, outbox processor);
  `worker` runs the loops and skips the serving-side caches; default `all`
  keeps the single-process shape. Split roles refuse the embedded profile
  loudly — there the loops exist nowhere else. Scaling API replicas now
  scales request capacity, not the number of PostgreSQL scanners.

### Build — the dependency set is now a fact, not a weather report (audit P1-3)

- **`uv.lock` is the single resolution** for Python 3.11–3.13 (the versions CI
  actually tests; `[tool.uv].environments`). `requirements-docker.lock` is its
  hash-pinned export for the production image (extras `cloud,postgres`), and
  `Dockerfile.api` installs third-party packages only from it with
  `--require-hashes`, then the project wheel with `--no-deps`, then proves the
  result with `pip check` inside the build. Two builds from the same inputs now
  install the same bytes.
- **CI keeps the chain honest** (`ci.yml` job `lock-check`): `uv lock --check`
  against `pyproject.toml`, re-export diffed against the committed
  `requirements-docker.lock`, and a fresh hash-verified install that must pass
  `pip check`. `security.yml` gains a `pip-audit` job over the locked pins
  (`--no-deps` — nothing to resolve, which is what used to time out).
- **The `[flink]` extra is gone because it never existed.** apache-flink 2.3.0 →
  apache-beam ≤2.61 caps `pyarrow<17` while core pins `pyarrow>=17`: a fresh
  `pip install .[flink]` could not resolve at all, and a lock covering it is
  mathematically impossible. The Flink job runs in its own interpreter inside
  the cluster image and imports nothing from agentflow; its manifest is now
  `src/processing/flink_jobs/requirements.txt` (the image build asserts the
  apache-flink pin matches `ARG FLINK_VERSION`), and the Safety scan reads that
  file instead of the extra.

### Security — tenant isolation was a schema that nobody created (audit P0-1)

**Breaking for operators: every serving table's key changes.** `tenant_id` now
leads the ClickHouse sorting key and the DuckDB primary key. ClickHouse cannot
prepend to an existing sorting key and `CREATE TABLE IF NOT EXISTS` silently
keeps the old one, so a store provisioned before this change is refused at
startup (`assert_tenant_key()`) rather than served. Migrate with
`python -m src.serving.provision --migrate`; a file-backed DuckDB store has no
in-place migration and must be rebuilt (`:memory:`, the default, is created
correctly). See [ADR-004](docs/decisions/004-tenant-id-column-over-schema-per-tenant.md).

- **The boundary did not exist.** Isolation was expressed as a *schema
  qualification* — `TenantRouter` mapped a tenant to a `duckdb_schema`, and the
  SQL builder rewrote `orders_v2` into `"acme"."orders_v2"`. Nothing in `src/`
  ever issued `CREATE SCHEMA`: only test fixtures did. So on DuckDB every
  *authenticated* entity read died on a relation that was never created, and on
  ClickHouse the same name meant a database nobody creates. The suite was green
  because the shipped keys named `acme-corp`, a tenant absent from
  `config/tenants.yaml` — the qualification resolved to nothing and silently did
  not apply. A boundary no test can tell apart from its own absence is not one.
- **Worse than a leak: data loss.** Drop the qualification and both tenants share
  one `ReplacingMergeTree` key — two rows with the same `order_id` are two
  *versions of one row*, and the later insert destroys the earlier. No read-side
  filter can undo that, which is why the boundary is now in the physical schema
  and the write key rather than only in a predicate.
- **One model, both stores.** `tenant_id` is a column on all five serving tables.
  Reads go through a single chokepoint: `_qualify_table` returns a tenant-filtered
  sub-select (`SELECT * EXCLUDE (tenant_id) ... WHERE tenant_id = ...`) aliased
  back to the table's own name, and `_scope_sql` performs the same substitution
  inside metric templates and NL-generated SQL over the sqlglot AST. Writes stamp
  the tenant (`event_tenant()`); aggregates group by it — a global
  `GROUP BY user_id` had been summing two tenants' orders into one total and
  writing it back to both. Search carries the tenant on each document and filters
  before scoring. An unscoped read against a store holding foreign-tenant rows is
  refused (503), not answered.
- **`duckdb_schema` is gone** from `TenantDefinition`, `config/tenants.yaml` and
  the chart's shipped values; `TenantRouter.get_duckdb_schema()` is deleted. The
  Helm values schema still *accepts* the key (tenant items are
  `additionalProperties: false`, so removing it would reject values written for
  the old model) and its description says it is ignored.
- **Proven, per store.** DuckDB: two tenants with identical entity ids resolve to
  different rows, cross-tenant lookups 404, aggregates scope, unscoped reads are
  refused — by example (`tests/integration/test_tenant_isolation.py`) and over
  generated tenant/entity ids (`tests/property/test_tenant_isolation_properties.py`).
  ClickHouse: `tests/integration/test_clickhouse_tenant_isolation_live.py` plants
  both tenants in one live store with the same `order_id`, `user_id`,
  `session_id` and `product_id`, then drives entity, timeline, metric, historical,
  NL, pagination, batch, search, lineage and SLO under both keys, plus qualified-SQL,
  CTE-shadowing and recursive-CTE escape attempts.
- The tenant-id validator accepted `"acme\n"`: Python's `$` also matches *before*
  a trailing newline, so an anchored `.match()` let a string that is a different
  tenant than `acme` through, to become its own silent partition. It uses
  `fullmatch` now. Found by the property suite, which is the point of having one.
- `scripts/restore.py` asserted that a restored store had a *schema per tenant*,
  parsed out of the `duckdb_schema` field — and the backup workflow's fixture
  fabricated exactly those schemas, so the check passed only because the fixture
  had made it pass. Both now use the product's own DDL: the fixture writes two
  tenants into one `tenant_id`-keyed table, and restore asserts that the serving
  tables come back carrying the column — and **refuses a pipeline store with no
  serving tables at all**, which the old check accepted in silence.

### Fixed — half the API answered from a store nobody was serving (audit P0-3)

**Breaking for operators: the Kubernetes probes and the Compose healthcheck move
off `/v1/health`.** Readiness is now `/health/ready` and liveness `/health/live`;
`/v1/health` stays as the agent-facing informational payload.

- **`/v1/lineage`, `/v1/slo`, `/v1/search` and the health collector read the
  embedded DuckDB directly**, whatever `SERVING_BACKEND` said. On the ClickHouse
  profile the API therefore split in half: entity and metric answered from
  ClickHouse, while lineage reconstructed provenance, SLO computed an error
  budget, and health reported freshness — all from a DuckDB that held nothing
  but demo rows. Lineage even labelled the enrichment layer `system="duckdb"` on
  a ClickHouse deployment. A plausible wrong answer is worse than an outage.
- New `semantic_layer/journal.py` (`JournalReader`): every `pipeline_events`
  read goes through `ServingBackend`. `QueryEngine.backend` / `.journal` are the
  public front doors, and a **static ratchet test now fails on any private reach**
  (`query_engine._conn`) from a read surface. A behavioural test injects a
  backend holding rows that exist nowhere in DuckDB and asserts every surface
  returns *those* rows.
- **The health collector never checked the serving store at all** — it checked
  Kafka, Flink and Iceberg, and opened its own read-only DuckDB at `DUCKDB_PATH`
  for freshness and quality (an unrelated database on the ClickHouse profile, a
  brand-new empty one on the `:memory:` default). It now has a `serving`
  component and reads the journal through the active backend.
- **`/v1/health` always answered 200** — its status lives in the payload — and
  both Kubernetes probes *and* the Compose healthcheck pointed at it, so a
  replica with a dead ClickHouse looked healthy to every orchestrator watching
  it. `/health/ready` answers 503 when the serving store is unreachable *or
  unprovisioned* (the readiness error that P0-2's removal of boot-time DDL makes
  possible); `/health/live` stays dependency-free, so a ClickHouse outage cannot
  roll every pod. `ControlPlaneStore.ping()` added (no-op on embedded,
  `SELECT 1` on PostgreSQL).
- The search index's entity scan is bounded (`AGENTFLOW_SEARCH_SCAN_LIMIT`,
  default 10 000) and logs truncation. It was an unbounded `SELECT *` that grew
  with the serving data — the next RSS-growth candidate after the webhook poller
  (audit P1-6).
- ClickHouse transpile gained `quantile_cont(col, q)` → `quantile(q)(col)`: the
  SLO latency SLI was the one journal read with no valid ClickHouse translation.
- The image's own `HEALTHCHECK` moved off `/v1/health` too. Helm and
  `docker-compose.prod.yml` had been switched, but `Dockerfile.api` still asked
  the endpoint that always answers 200 — so a standalone container reported
  itself healthy while its serving backend was unreachable and every read was
  failing. It asks `/health/ready` now, which can say no.

### Changed — provisioning is a writer privilege, not a boot side effect (audit P0-2)

**Breaking for operators of the ClickHouse profile: the API no longer creates
its own tables.** Run `python -m src.serving.provision --schema` once before the
first boot (Compose and Helm now do it for you — see below).

- **`QueryEngine.__init__` ran DDL and seeded demo rows on every boot**, against
  the embedded store *and* whatever external backend was configured — before
  anything read `AGENTFLOW_DEMO_MODE`, which is why the flag appeared to do
  nothing. Consequences: the serving identity needed CREATE/ALTER/INSERT on the
  production store, several booting replicas could each see an empty table and
  seed it, and a fresh production ClickHouse got demo orders for no better
  reason than being empty.
- The constructor now only lays down the *embedded* schema (that store is
  created in-process and has no other provisioner). It sends **nothing** to an
  external backend — pinned by a test that fails if a single statement reaches
  ClickHouse on boot. An API image can run against a read-only ClickHouse user.
- Seeding is opt-in via `AGENTFLOW_SEED_ON_BOOT` (default off), independent of
  `AGENTFLOW_DEMO_MODE`, which keeps its own meaning (public demo key +
  read-only guard).
- **New: `python -m src.serving.provision [--schema] [--seed]`** — idempotent,
  re-runnable, and provisions every store the API reads (on the ClickHouse
  profile the embedded DuckDB still holds control-plane state, so both get their
  schema). Wired into `make demo`, a `serving-init` one-shot service in
  `docker-compose.prod.yml`, and a Helm `pre-install`/`pre-upgrade` migration
  Job. A failed migration now fails the release instead of letting pods come up
  against a store they would have silently created.
- Helm gained `serving.clickhouse.migrationUser` / `migrationPasswordKey` so the
  DDL identity can be separate from the serving one, and `provision.enabled` /
  `provision.backoffLimit`.
- **The bridge writer no longer seeds either.** `ClickHouseSink` still ensures
  the schema — it holds the write grants and cannot run without the tables — but
  it does not decide an empty store deserves demo rows.

### Security — `/v1/search` enforced the entity allowlist on nothing (audit P0-4)

- **A scoped API key could read every entity type through `/v1/search`.**
  `SearchIndex.search()` returns mappings; the router post-filtered them with
  `getattr(result, "entity_type", None)`, which is always `None` for a `dict`,
  so the `or` short-circuited and every forbidden row passed. A key limited to
  `order` got `user`, `product` and `session` ids **and snippets** back whenever
  it sent no explicit `entity_types` filter. The direct entity endpoints kept
  answering 403 — only search leaked. Reproduced against the real index (not a
  mock) before the fix: `assert {'product', 'session', 'user'} == set()`.
- The allowlist is now enforced **inside the index, before scoring**, so a
  forbidden document never enters the candidate set. This also closes a second
  defect: the old post-filter ran *after* `[:limit]`, so forbidden documents
  consumed result slots and could crowd out every row the key was allowed to
  see.
- Policy is now explicit and tested: entity and `catalog_field` documents follow
  the key allowlist; metric documents stay visible to scoped keys because
  `/v1/metrics/*` is not entity-scoped; an empty allowlist returns no
  entity-scoped document at all.
- `SearchIndex.search()` returns `list[SearchHit]` (a `TypedDict`) instead of
  `list[dict]`, so mypy now rejects the attribute access that silently disabled
  the filter.

### Added — Flink state backend is configurable (unblocks stand throughput runs)

- The Flink `state.backend.type` in `docker-compose.yml` is now
  `${FLINK_STATE_BACKEND:-rocksdb}` for both JobManager and TaskManager.
  Production and CI keep the RocksDB default (incremental checkpoints, off-heap
  state); a stand can export `FLINK_STATE_BACKEND=hashmap` to run the small
  dedup/TTL state in heap. Offered as a candidate workaround for a
  RocksDB-async-checkpoint native TaskManager crash observed on a constrained
  macOS/Lima Intel VM during a sustained-throughput window (root cause
  unconfirmed — may be the VM kernel, so this is a lever to try on the stand,
  not a proven fix). The default is unchanged, so CI `flink-smoke` keeps
  exercising RocksDB.

### Fixed — webhook dedup and cache-scan window (audit #184-186)

- **Webhook dispatcher** dropped a dead bare-`event_id` membership test — the
  seen-set only ever holds `tenant:event_id`, so dedup is strictly per-tenant
  (regression test added).
- **Startup scan cursor** now seeds from the newest journal row whose
  `processed_at` parses, not blindly the newest row: a malformed newest
  timestamp left the cursor `None`, which made the first scan fetch from the
  oldest row and re-deliver the seeded batch.
- **Metric-cache scan window** raised 200 → 2000 rows
  (`DEFAULT_SCAN_WINDOW_ROWS`). At the ≥100 eps target the pre-merge journal
  emits ~2 rows/event, so 200 left no margin for a non-pushing writer; push
  feeds still cover writers that publish.

### Fixed — SSE per-connection dedup cache is bounded (issue #183 follow-up)

- **`/v1/stream/events` kept a bare per-connection seen-set** that grew one
  entry per distinct event for as long as the SSE connection stayed open —
  the same disease as #183, scoped to a connection (hours of sustained
  traffic ⇒ hundreds of MB per open stream). Now a `BoundedSeenSet`
  (`SEEN_CACHE_SIZE` = 10 000). Eviction cannot re-emit an event: the scan
  window is the newest 10 rows, so an id leaves the window after 10 newer
  events but leaves the cache only after 10 000 newer distinct ids. Unit
  tests pin the bounded cache and the eviction-safety behavior.

### Fixed — API journal scans are bounded; steady-load RSS no longer grows with the journal (issue #183)

- **The webhook dispatcher's 2-second poll re-materialized the entire
  `pipeline_events` journal on every pass** (`fetch_pipeline_events` with no
  limit). The S11 endurance soak grew the journal to ~683 k rows and the API
  process to **1.67 GB RSS in 4 h** while the bridge on the same host stayed
  flat. Measured at unit scale: one scan allocated 35.5 → 283.6 MB as the
  journal grew 50 k → 400 k rows. The scan is now incremental and bounded — at
  most `scan_batch_size` (1000) rows at/after a `processed_at` cursor
  (`min_processed_at`, new `fetch_pipeline_events` parameter; strictly parsed,
  inclusive, second-floored). The cursor freezes at the first event whose
  durable enqueue failed, preserving the retry-forever delivery semantics of
  the full scan, and an all-seen full batch still advances it, so a wide seen
  frontier cannot pin the window. Post-fix the same measurement is flat
  ≤ 0.8 MB per scan. Startup seeding (`mark_existing_events_seen`) is
  O(batch), not O(journal).
- **The scan/push dedup sets kept one entry per event forever** — both
  `WebhookDispatcher.seen_event_ids` and `MetricCacheController`'s seen ids
  (which the Redis push feed grows with every applied batch). Both are now
  `BoundedSeenSet`s (`src/serving/seen_events.py`) — capped, FIFO-with-refresh
  eviction; safe because webhook enqueue is idempotent on its primary key and
  a redundant cache invalidate merely repopulates on the next read.
- **Found while fixing: the metric-cache journal-scan fallback was dead on
  grown journals.** The lifespan wired it as an ascending limited scan — the
  *oldest* 200 rows, a window that stops changing once the journal outgrows
  it — so scan-driven invalidation silently stopped detecting new events
  (Redis push kept the soak drift-free, which masked it). `journal_scan_fetch`
  now reads the `newest_first` tail window; a regression test pins detection
  on a journal larger than the window.
- **Verified live 2026-07-11:** 97 min at the soak read/apply profile against
  a journal preloaded to 1.37 M rows (2.5× the size that exposed the leak) —
  RSS slope **+7.5 MB/h, plateaued** (was ~+370 MB/h monotonic); FDs pinned;
  0 read errors (`docs/perf/rss-reverify-183-2026-07-11.md`). The mechanism
  is pinned at the unit layer in `tests/unit/test_webhook_dispatcher_unit.py`,
  `tests/unit/test_cache_invalidation.py`, `tests/unit/test_seen_events.py`,
  and `tests/unit/test_pipeline_events_scan.py`.

### Added — S13: at-scale proof on the project's own generator

- **`scripts/benchmark_scale_own_data.py`** scales the kitchen-legend history
  in-database (ClickHouse `numbers()` INSERT-SELECT, deterministic, the real
  checked-in raw-vault DDL) and measures load rate, analyst-query latency,
  and the generator-spec §12 invariants in SQL at volume. Run on the stand at
  `--days 1460`: **51.2 M rows / 2.87 M orders / 10.66 M marking codes**
  generated at 845 k rows/s, analyst queries 20–730 ms median, **all 17
  correctness checks pass** including a full-scan GS1 mod-10 validation of
  every GTIN (`docs/perf/scale-own-data-2026-07-11.md`). The at-scale claim
  retired with the external dataset (G2 S2b, 2026-07-05) is thereby restored
  on own data. CI exercises the harness end-to-end at `--days 2` in the
  live-ClickHouse job (`tests/integration/test_scale_own_data_smoke.py`).

### Fixed — a usage-accounting write could turn a served request into a 500

- **The usage database is now opened once per process.** Every authenticated
  request appends an `api_usage` row from a worker thread, and the
  analytics/admin routers build a throwaway `EmbeddedControlPlaneStore` per
  request; each of those used to call `duckdb.connect()` on the same file. The
  last close destroys the DuckDB instance, so a close racing an open left the
  file briefly attached by two instances and DuckDB raised
  `BinderException: Unique file handle conflict`. `EmbeddedControlPlaneStore`
  now keeps one owning connection per usage-db path and hands out `.cursor()`
  children — the shape `DuckDBPool` already uses for the serving database.
  Callers are unchanged: they still `close()` what they are given, and closing
  a cursor leaves the connection alive. Measured on the store's own path: 80
  concurrent usage writes went from 80 physical connects to 1.
- **The exception no longer reaches the client.** `record_api_usage` still
  raises on exhausted retries — `record_usage` depends on that to skip its
  audit publish — but `AuthMiddleware` now catches it, increments the new
  `agentflow_usage_record_failures_total` counter, logs
  `api_usage_record_skipped`, and serves the request. Accounting is a
  side-channel; a dropped row must not fail the request it was counting.
- Caught by the Load Test on `main` (2026-07-09): 19 of 1712 requests returned
  500 across all six endpoints, each with `record_api_usage → connect_duckdb`
  in the traceback. Regression tests pin both invariants
  (`tests/unit/test_usage_db_connection_reuse.py`,
  `tests/unit/test_auth_usage_write_failure.py`); the race's timing reproduces
  only on the CI runner, so the tests pin the mechanism that removes it.

### Changed — one Flink version across pip extra and container runtime (audit 07.07 F2)

- **The Docker runtime moves 2.2.1 → 2.3.0**, matching the `[flink]` extra
  (`apache-flink==2.3.0`, bumped in #87 and smoke-validated since): the
  `flink_jobs` image ARG (`FLINK_VERSION`, which also drives the pip install
  and the `flink-s3-fs-hadoop` plugin symlink) and both official cluster
  images in `docker-compose.yml` (`flink:2.3.0-java17`). Developing locally
  against a 2.3.0 PyFlink while the cluster ran 2.2.1 could surface behaviour
  that did not exist on the deployed minor; the two lines are now one.
- **The Kafka connector stays `flink-sql-connector-kafka-5.0.0-2.2`** — the
  externalised connector is versioned `<connector>-<flink minor>` and no
  `-2.3` build is published. Flink keeps `@Public` API stable within a major,
  so the 2.2 artifact runs on a 2.3 cluster; the Dockerfile says so, and
  `flink-smoke` submits `stream_processor.py` to a real Kafka+MinIO+Flink
  cluster on every PR, so the combination is asserted rather than assumed.
- `docs/architecture.md` Technology Choices now reads Flink 2.3. Historical
  records (CHANGELOG entries, `docs/perf/freshness-realpath-2026-06-30.md`)
  keep the version they were measured on.

### Changed — the published SDK is under the same lint gate as `src/` (audit 07.07 F1)

- `ci.yml` runs `ruff check` and `ruff format --check` over `sdk/` as well;
  the one-off reformat touched `async_client.py`, `cli.py`, `client.py`
  (line-collapse only). `make lint` / `make format` now cover
  `src/ tests/ scripts/ sdk/`, so local and CI agree.

### Fixed — the standalone API image could bake in secret-bearing config and ran as root (audit P1-4)

- `Dockerfile.api` did `COPY config /app/config` with no allowlist, while
  `pyproject.toml` already excludes `config/api_keys.yaml`,
  `config/webhooks.yaml` and `config/tenants.yaml` from the sdist for the
  same reason — they carry credential material (bcrypt key hashes, webhook
  signing secrets) or tenant routing data. `.dockerignore` didn't mirror that
  exclusion, so a future plaintext secret in one of those files would have
  been baked into an immutable image layer. `.dockerignore` now excludes the
  same three paths `scripts/check_release_artifacts.py` already treats as
  forbidden release-artifact members, so the existing `COPY config
  /app/config` can no longer see them. Compose and Helm are unaffected:
  Compose bind-mounts `./config:/app/config:ro` over the image, and Helm
  never reads `/app/config` at all — it mounts the real config/secret
  through a ConfigMap/Secret at `/etc/agentflow/config` and
  `/etc/agentflow/secret`.
- **The image ran as root by default.** Helm compensates
  (`containerSecurityContext.runAsUser: 10001`), but `docker run` without
  Helm did not. `Dockerfile.api` now creates a non-root `agentflow` user
  (uid/gid 10001, matching the Helm value) after all install steps and
  switches to it, pre-creating and chowning `/app/data` so a fresh Compose
  named volume mounted there inherits the right ownership on first use.
- New `tests/unit/test_docker_secret_policy.py` (static — Docker isn't
  available on this host): fails if `.dockerignore` ever stops excluding the
  three secret config paths, if `Dockerfile.api` ever `COPY`s one of them by
  name, or if the final image stage's last `USER` is root/uid 0.

### Changed — "Nightly Backup" is a regression test, not a backup, and now says so (audit P1-2)

**The workflow never touched a deployed environment.** It built synthetic
DuckDB fixtures on an ephemeral GitHub runner, tarred them, and uploaded a
7-day Actions artifact — a real check that the backup/restore code path
still works, but no evidence a live environment can be recovered. Calling it
"Nightly Backup" and citing an RPO/RTO in `docs/disaster-recovery.md` on the
strength of it was a false claim.

- The workflow is renamed **`Backup/Restore Regression Test`**
  (`.github/workflows/backup.yml`) and says up front, in a comment, what it
  actually is. Its GitHub Actions artifact is renamed from
  `agentflow-nightly-backup` to
  `agentflow-backup-restore-regression-fixture`. The job id (`backup`) is
  unchanged — `pyproject.toml`'s
  `[[tool.agentflow.dependency-profiles.targets]]` registry references it by
  `path` + `job`.
- `docs/disaster-recovery.md` no longer states a flat RPO/RTO. It says
  plainly what exists today — a DuckDB file/config backup+restore code path,
  exercised nightly against synthetic fixtures — and what does not:
  no ClickHouse backup, no PostgreSQL control-plane backup, and no restore
  ever measured against a real staging environment.
- `scripts/backup.py` swept all of `config/` into the archive, including
  `config/api_keys.yaml` — bcrypt key hashes, credential material — with no
  exclusion. It now reuses
  `scripts/check_release_artifacts.FORBIDDEN_MEMBER_PATTERNS` (the same list
  the Python release-artifact check already enforces) to skip
  `config/api_keys.yaml`, `config/webhooks.yaml` and `config/tenants.yaml`,
  plus anything else matching the same "secret" / `secrets/` patterns.
  `tests/unit/test_backup.py` builds an archive from a fixture tree
  containing all three, asserts none are archive members, cross-checks the
  result with `find_forbidden_members()`, and round-trips it through
  `scripts/verify_backup.py` and `scripts/restore.py` to confirm the rest of
  the pipeline still works without them.

## [2.0.0] - 2026-07-06

### Fixed — single-container demo deploys pin the DuckDB serving backend (G2 S7, 2026-07-06)

- **`SERVING_BACKEND=duckdb` is now pinned** in `deploy/hf-space/Dockerfile`
  (`ENV`), `deploy/fly/fly.toml` (`[env]`), and the `deploy/fly/README.md`
  local docker-run example. `config/serving.yaml` has defaulted to ClickHouse
  since the ADR 0006 Phase 1 cutover and ships inside the demo image, so any
  demo built from post-cutover main crashed on boot (`BackendExecutionError:
  connection refused` — no ClickHouse runs beside a single-container demo).
  Caught live on the first three-node HF Space bring-up; the standalone demo
  Space never showed it only because it still ran a pre-cutover image.

### Added — Three-node demo topology: center hub + two edge branches, live on HF Spaces (ADR 0012 — F1/F2 2026-07-04, deployed G2 S7 2026-07-06)

- **Node roles land in the serving API** (`AGENTFLOW_NODE_ROLE` = `center` |
  `edge`; standalone stays byte-identical without it). The center mounts
  `POST /v1/node/events` — bearer-token ingest, distinct from the public
  `demo-key` and hidden from the public OpenAPI catalog, applying each pushed
  event through the existing `_process_event` path — and
  `GET /v1/node/branches`, the cross-branch summary (seeded baseline, live
  delta, last-seen per branch, `waking` for silent ones). Edges run a
  background emitter that applies each generated event locally and forwards
  the same canonical dict to the hub; a cold hub is tolerated (bounded
  retries, then drop). The N1–N12 node invariants are pinned as
  unit/integration tests.
- **Deployed as three Docker Spaces** under the `liovina` account
  (`agentflow-center`, `agentflow-edge-spb`, `agentflow-edge-ekb`) from
  `deploy/hf-space/three-node/` — one shared image built from public `main`,
  role set purely by Space environment. Center + edge-spb live-verified
  end-to-end via the §12 checklist: auth ladder (401/403), `applied:1`
  token ingest, idempotent re-POST, cross-branch delta movement.

### Changed — spec/seed number consistency: daily rate, GTIN check digits, band centering, FX honesty (G2 S3, 2026-07-06)

- **Seed daily rate now matches §1 (audit m5).** `satellite_seed*.sql` order
  dates spread over a ~122-hour (≈ 5.1-day) flat window instead of 21 days:
  10,000 orders ≈ 1,965/day — generator-spec §1's baseline rate. §11 now
  documents that §4's monthly seasonality is deliberately not encoded in a
  5-baseline-day seed (a 5-day snapshot cannot express a 12-month curve).
- **Vault-seed GTINs are valid GTIN-13 (audit m6).** `synthetic_seed.sql`'s
  `gs1_gtin` values now append the genuine GS1 mod-10 check digit via a
  pinned 160-digit string, asserted against `reference/gs1.py`'s
  `gtin13_check_digit` by a new invariant test — §12 #7 now holds for the
  vault seed too, not only the reference catalog.
- **Amount bands re-centered on §1's average checks (audit m7).** The old
  equal-width bands ran ~5% (dxb: ~12%) above target; new bands are centered
  and multipliers re-chosen so small branch slices equidistribute:
  marketplace 1.5k–2.8k (mean ≈ 2,150), D2C 2k–4.6k (≈ 3,300), B2B RU
  30k–74k (≈ 52k), dxb 60k–120k (≈ 90k), ala 25k–65k (≈ 45k).
  `postgres_oltp/seed.sql` mirrors the same formulas.
- **§12 #4 no longer contradicts §1; invariant tests tightened (audit m4).**
  §12 #4 now claims the order-weighted aggregate B2B avg check (≈ 54.9k ∈
  [30k, 80k]) and names dxb's 90k export-pallet check as the by-design
  outlier. Tests now assert the aggregate averages (not only per-branch
  proxies) and pin the spec-fixed defaults: 160 SKUs, 30 suppliers
  (22 CN + 5 RU + 2 AE + 1 KZ), sourcing coverage for every SKU.
- **§10 FX constants declared documentation-only (audit n2).** §1/§10 now
  state that every branch is seeded in ₽ and no generator or seed performs an
  FX conversion at runtime; the pinned AED/KZT/CNY constants remain in
  `reference/legend.py` solely as the fixed basis for doc/evidence-level
  conversions.

### Changed — demo narration and evidence re-captured live on the kitchen legend (G2 S5/S6/S8, 2026-07-05/06)

- **Narration texts rewritten off the fashion-retailer legend**
  (`demo_voiced.narration.txt`, `demo_transcript.txt`) onto the importer's
  real pains — cross-channel oversell, container ETA, five-program triage
  (`domain.md` §4); the voiced demo mp4 re-recorded live on the current
  legend (the webui capture was already legend-clean).
- **DV2 evidence re-captured on a live kind stand** (§1–3, §9, §10,
  §12–§15), catching and fixing two real bugs in the process:
  `cdc_setup.sql` now grants `CREATE` on the source DB to `rep_user`, and
  the MinIO `mc`-alias setup was repaired. The load-test baseline was
  re-captured at seed scale with an explicit host-contention caveat; the
  live 2-pod ClickHouse cutover stage is documented as blocked by stand
  contention, with the re-run recipe pinned
  (`docs/clickhouse-cutover-plan.md` Phase 3, ADR 0010).
- **Delta re-audit followups (S8)**: stale factual claims corrected (probe
  counts, node-label narration, done-status notes), residual USD tails
  re-pinned to ₽, the retired dataset's name dropped from provenance
  comments.

### Changed — hardening: bounded journal scans and a node-token guard (G2 S4, 2026-07-06)

- **Journal scans are bounded and deterministic**: the newest-first scans in
  `ops.py` / `reconciliation.py` carry an explicit `LIMIT` and tiebreak
  equal timestamps on `event_id`; `fetch_pipeline_events(None)` scoping
  tightened.
- **`AGENTFLOW_NODE_TOKEN` may not equal the public demo key** — enforced by
  a boot-time guard rather than convention.

### Removed — X5 Retail Hero loader deleted; at-scale benchmark retired as historical (G2 S2b, 2026-07-05)

- **Deleted `warehouse/agentflow/dv2/loaders/x5_retail_hero/`** in full
  (`loader.py`, `mappers.py`, `schemas.py`, `branch_distributor.py`,
  `README.md`, `requirements.txt`) and its dedicated test
  `tests/unit/test_x5_retail_hero_loader.py`. Per the project owner's
  override, the "X5 Retail Hero" dataset — a real external grocery
  retailer's public Kaggle dataset that the demo's synthetic legend never
  needed — must not appear anywhere in the project going forward; this
  changelog entry is the one place that name may still be written. No
  successor bulk generator is built (S2a decision, formerly
  `x5-benchmark-decision.md`, deleted in this same step once executed):
  demo-scale raw-vault data is fully covered by
  `warehouse/agentflow/dv2/synthetic_seed.sql` +
  `satellite_seed_all_branches.sql`, the kitchen live generator
  (`src/ingestion/`), and `reference/load_postgres.py`.
- **At-scale load-test benchmark retired as historical.** The 2026-06-07
  ClickHouse capture (tens of millions of raw-vault rows, loaded from the
  now-deleted dataset) is no longer presented as a current baseline. The
  load-test harness (`infrastructure/dv2/load-test/`) stays fully runnable
  and gating against the synthetic demo seed unchanged (including the
  `P99_MS_POINT=250` budget, whose queueing rationale is preserved in
  `job.yaml`'s comments). `docs/dv2-multi-branch/load-test-baseline.md` now
  documents only the seed-scale baseline; the retired capture's three
  engineering findings (`customer_360` sort key, `uniq()` vs `uniqExact()`,
  the point-budget queueing analysis) are summarized there and the full
  report is preserved in this file's git history.
- **Test surgery**: the vault-generic row models used by both
  `tests/unit/test_dv2_postgres_ingestion.py` (the only coverage for
  `PostgresVaultWriter`) and the deleted loader now live in
  `warehouse/agentflow/dv2/loaders/vault_rows.py`. The loader-sink tests
  (`_open_sink` / `_DryRunSink` / `_PostgresSink` / `_ClickHouseSink`) are
  removed along with the loader. `tests/unit/test_dv2_supplier_reference.py`'s
  hash-equality pin now checks `vault_mapping`'s own MD5 canonicalisation
  against precomputed known-vector digests instead of importing the deleted
  loader; `test_dv2_business_vault_ddl.py` / `test_dv2_postgres_ddl.py` drop
  the "`x5__` not in DDL" regression guard (the check string itself would
  violate the no-X5-anywhere rule) and keep the positive "`mp__` in DDL"
  assertion.
- **De-branded** every remaining reference across `spec.yaml` (and its 10
  generated satellite DDL files), the dbt config (`sources.yml`, `README.md`,
  `profiles.example.yml`), `docs/domain.md`, `docs/dv2-multi-branch/{schema_dv2,demo_evidence}.md`,
  `docs/generator-spec.md`, `docs/operations/{aws-oidc-setup,openssf-security-posture}.md`,
  `docs/perf/vault-pii-governance-pg-verify-2026-07-0{2,3}.md`,
  `infrastructure/dv2/{clickhouse-sts.yaml,dbt/dbt-run-job.yaml,load-test/*}`,
  and the DV2 loader/reference Python docstrings (`pg_vault_writer.py`,
  `vault_mapping.py`, `reference/README.md`, `reference/load_postgres.py`,
  `postgres_oltp/README.md`, `dv2/README.md`) — no "X5" / "Retail Hero" /
  retired at-scale row-count strings ("45.8M", "8.06M", "402K") survive
  outside this file and git history.

### Changed — residual USD/generic-catalog text swept to the kitchen/₽ legend (G2 S1, 2026-07-05)

- Entity contracts (`product`, `user`) price text moved to ₽ (the stable
  contract's `Currency` enum keeps `[RUB, USD, EUR, GBP]` with RUB default —
  no version bump); the agent-demo notebook, EUR/GBP test fixtures,
  `docker/postgres-source/init.sql`, the NL-SQL eval warehouse, and the
  benchmark/load-test catalogs re-pinned to the kitchen catalog per
  generator-spec §3/§9.

### Changed — demo legend re-pinned: own-brand kitchen-appliance importer in ₽ (A1/A2 + B1–B4 + C1 2026-07-03, G2 B1 2026-07-05)

- **`domain.md` becomes the business-legend source of truth** — an own-brand
  kitchen-appliance importer selling through five sales programs — with the
  unit-economics and data-generation specs pinned alongside (A1/A2).
- **Generator + seeds rebuilt on the legend** (B1), `record_source` examples
  renamed off the retired brand (B2), the serving demo store re-pinned (B3),
  `demo_evidence.md` regenerated with a fresh `verify_live` (B4), DV2 docs
  swept of the clothing/footwear storyline (C1), and the live generator +
  currency defaults moved to kitchen/₽ (G2 B1 fix-batch).

### Added — bv_order_canonical PostgreSQL smoke: seed + verify (G1, 2026-07-04)

- `verify_bv_order.sh` seeds a canonical order into the PG raw vault and
  verifies the business-vault projection end-to-end; transcript captured
  live on the kind stand (17/17 checks, G2 S6, `docs/perf/`).

### Added — operational read surfaces: Order 360, stuck-orders worklist, exception inbox (D2/D3/D4, 2026-07-04)

- **Order 360 timeline** endpoint + stage-entry journal (D2), the
  **stuck-orders worklist** with its SLA-stage contract block (D3), and the
  **exception inbox** — a dead-letter/webhook overlay with R1/R2
  reconciliation (D4): the three ops surfaces ADR 0011 splits out of the
  agent-facing catalog.

### Added — Helm PostgreSQL control-plane profile; shared TenantRouter (ADR 0010 slice 6 / E4 + E3, 2026-07-04)

- The chart renders the scale profile (external PostgreSQL control plane)
  behind the render-time scaling gate (E4); tenant routing extracted into a
  shared `TenantRouter` module and the warehouse gitignore split (E3).

### Added — Operational serving split decided; ops-surfaces spec (ADR 0011, 2026-07-03)

- **New [ADR 0011](docs/decisions/0011-ops-serving-split.md)** — the design
  decision for the operational layer (`docs/domain.md` §4): every ops surface
  (Order 360 timeline, stuck-orders worklist, exception inbox) composes
  exactly the two existing ports — `QueryEngine`/`ServingBackend` for
  analytical reads, `ControlPlaneStore` for transactional triage state — with
  no third data path (no `query_engine._conn`, no vault DSN). Options
  considered and rejected with reasons: everything-on-ClickHouse,
  everything-on-PostgreSQL, direct vault reads for the customer block,
  precomputed ops marts. The exception-triage overlay is recorded as the
  seventh control-plane state class, extending ADR 0010's inventory.
- **New `docs/ops-surfaces-spec.md`** — the implementation contract for
  slices D2–D4: SLA stage model with budgets as catalog data (a `stages:`
  block in `contracts/entities/order.yaml`), stage-entry journal rows
  (`orders.status` topic) as the stage clock with an honest `created_at`
  fallback, the journal's `entity_id` axis made real on live writes, endpoint
  contracts and response shapes for `/v1/entity/order/{id}/timeline`,
  `/v1/ops/stuck-orders`, and `/v1/ops/exceptions` (+stats), reconciliation
  checks R1/R2, the manual-resolutions counter, a pinned demo story
  (ORD-20260404-1004 as the sole SLA breach), and twelve machine-checkable
  invariants as the test ТЗ.
- Docs-only: no runtime behavior changes in this entry.

### Added — PostgresControlPlaneStore: the scale profile ships (ADR 0010 slice 5, 2026-07-03)

- **New `src/serving/control_plane/postgres.py`** — all six control-plane
  state classes as PostgreSQL tables behind the existing port, with the claim
  semantics the embedded adapter only satisfies degenerately made real:
  enqueue-win by `INSERT .. ON CONFLICT DO NOTHING` rowcount, queue/outbox
  claims by `FOR UPDATE SKIP LOCKED` + a self-expiring `lease_expires_at`
  (work-stealing across replicas, no leader election; a crashed owner's rows
  become due again on lease expiry), invariant 8 as an ordinary transaction
  (every store method is one transaction: commit on success, rollback on any
  exception). Payloads stay TEXT/JSON-string so callers see the embedded
  adapter's shapes. One connection per call — pooling stays out of ADR scope.
  Selection: `AGENTFLOW_CONTROLPLANE_STORE=postgres` +
  `AGENTFLOW_CONTROLPLANE_PG_DSN` (+ optional
  `AGENTFLOW_CONTROLPLANE_LEASE_SECONDS`); the slice-1 `NotImplementedError`
  ratchet is gone, and a missing DSN or missing `psycopg` fails the boot
  loudly — never a silent fallback to embedded. `psycopg` is a new optional
  extra (`pip install agentflow-runtime[postgres]`), the `redis` import
  pattern.
- **Webhook registrations (state class 5) move behind the port** — the
  sharpest split-brain of the ADR's inventory was still a per-pod YAML read
  outside the port after slices 1–4. New port methods
  `load_webhook_registrations`/`save_webhook_registrations`;
  `load_webhooks`/`save_webhooks`/`create_webhook`/`list_webhooks`/
  `get_webhook`/`deactivate_webhook` now take `app` and resolve the store
  inside (the same move the alert-rule helpers made in slice 2). The embedded
  adapter keeps the byte-compatible `config/webhooks.yaml`.
- **Alert-tick single-flight (ADR 0010 §2) wired into the dispatcher** — new
  port methods `claim_alert_tick`/`complete_alert_tick`;
  `AlertDispatcher.dispatch_alerts` claims each rule before evaluating (a
  lost claim = another replica owns that rule's tick) and persists advanced
  rule state **per rule** in the same transaction as the claim release — the
  old full-set save would let two replicas advancing different rules clobber
  each other's runtime state. Embedded grants every claim (one process), so
  the single-replica profile behaves as before; a CRUD full-set save on
  PostgreSQL upserts by id and does not release an in-flight claim.
- **The postgres profile shares one store across every consumer**: `main.py`
  injects the app-wide store into `AuthManager` and `OutboxProcessor` when
  the profile is external (embedded keeps its historical private stores);
  the analytics entry points (`analytics.py`, `routers/admin.py`,
  `admin_ui.py`'s QPS tile) accept the store handle and route through
  `AuthManager.store`, so usage/sessions land in PostgreSQL instead of a
  per-pod DuckDB file.
- **Verified live (standalone PostgreSQL 17.5, no Docker): 31/31 probes** —
  the ADR's named suite (parallel claim exclusivity, lease-expiry re-drive,
  restart re-drive, enqueue-win uniqueness, outbox↔dead-letter atomicity
  incl. rollback halves, alert-tick single-flight) plus a full contract
  parity sweep and an end-to-end app test (two boots on the postgres profile
  see each other's webhook registration; usage accounting lands in PG):
  `docs/perf/control-plane-pg-verify-2026-07-03.md`. The same suite runs in
  CI against a new `postgres:17` service in the integration job and
  self-skips where `AGENTFLOW_TEST_PG_DSN` is absent.
- Helm is untouched by design: the values schema still pins
  `controlPlane.store=embedded` and the chart still refuses multi-replica
  renders — the enum extension and env/secret wiring are rollout slice 6,
  which this slice unblocks.

### Added — API-usage accounting and session analytics behind the ControlPlaneStore port (ADR 0010 slice 4, 2026-07-02)

- **`api_usage`** (per-tenant/per-key request counters) and **`api_sessions`**
  (per-request latency/entity/query telemetry) moved behind
  `ControlPlaneStore`. Unlike every prior slice, this state was never on
  `query_engine._conn` — `AuthManager.db_path` always resolves to its own
  DuckDB file, independent of `DUCKDB_PATH` — so `EmbeddedControlPlaneStore`
  gains a second, orthogonal `usage_db_path_provider` alongside its existing
  `conn_provider`/`alert_rules_path_provider`, and `AuthManager` builds a
  private embedded store bound to its own path (mirrors `OutboxProcessor`'s
  additive-`store` pattern) rather than sharing the app-wide store.
- **Scope widened past `usage_table.py` + `analytics.py`**: `KeyRotator`
  (`key_rotation.py`) queried `api_usage` directly for old-key-usage stats,
  and the admin dashboard (`admin_ui.py`) queried `api_sessions` directly for
  its QPS tile — both bypassed every prior slice's port and are covered here
  too, so a PostgreSQL swap (slice 5) doesn't leave two call sites hard-wired
  to a local DuckDB file.
- `record_usage`'s Windows file-lock fallback (temp-path rename on
  `duckdb.IOException`) and `record_api_session`'s best-effort
  log-and-return-on-exhaustion (vs. `record_api_usage`'s raise, which
  `record_usage` depends on to skip its post-insert audit publish) both moved
  into the store verbatim. `usage_table.py` / `analytics.py` / `key_rotation.py`
  / `admin_ui.py` keep their pre-port public/test-facing signatures — only
  the SQL and connection handling moved.
- New `EmbeddedControlPlaneStore` methods: `ensure_usage_schema`,
  `record_api_usage`, `get_usage_by_tenant`, `get_usage_by_key`,
  `get_old_key_usage_by_key_id`, `record_api_session`, `get_usage_analytics`,
  `get_top_queries`, `get_top_entities`, `get_latency_analytics`,
  `get_anomalies`, `get_queries_per_second_last_minute`.

### Added — Replay outbox + dead-letter behind the ControlPlaneStore port (ADR 0010 slice 3, 2026-07-02)

- **Invariant 8 preserved verbatim**: `mark_outbox_sent` flips an outbox row
  to `sent` and its dead-letter row to `replayed` in one transaction;
  `schedule_outbox_retry` bumps attempts/backoff or parks both rows `failed`
  once retries are exhausted, also in one transaction. Both moved into
  `EmbeddedControlPlaneStore` byte-for-byte (same SQL, same
  BEGIN/COMMIT/ROLLBACK shape) — confirmed by the existing rollback-simulation
  tests (table-drop and connection-wrapper fault injection) passing unchanged.
- `OutboxProcessor` and `EventReplayer` gain an additive `store:
  ControlPlaneStore | None = None` constructor kwarg; when omitted (every
  existing call site) they build a private embedded store bound to whichever
  `conn`/`duckdb_path` they already owned — preserving `main.py`'s
  `:memory:`-vs-file dual-connection split verbatim. `routers/deadletter.py`
  now resolves the app's shared store and passes it via `store=`, so it never
  reaches `query_engine._conn` directly (stats/list/detail/replay/dismiss all
  routed through new store methods).
- `ensure_outbox_table` / `ensure_dead_letter_table` moved to
  `control_plane/embedded.py` (same location as their webhook/alert
  siblings); `ensure_outbox_table` is deliberately NOT called lazily inside
  the write-transaction methods above (unlike the webhook/alert log methods)
  — it and `ensure_dead_letter_table` run once at `OutboxProcessor` /
  `EventReplayer` construction via a new `ensure_outbox_schema` port method,
  matching the pre-port eager-DDL timing exactly.
- Structural ratchet test extended to `src/processing/outbox.py`,
  `src/processing/event_replayer.py` and `routers/deadletter.py`. New
  `tests/unit/test_control_plane_store.py` coverage for the outbox/
  dead-letter store methods (claim ordering, mark-sent + rollback,
  retry/backoff/kafka-floor, replay enqueue + rollback, tenant-scoped
  reads, stats).

### Added — Alert history + alert-rule repository behind the ControlPlaneStore port (ADR 0010 slice 2, 2026-07-02)

- **Alert delivery history** (`alert_history`) moved behind `ControlPlaneStore`
  (`log_alert_delivery` / `get_alert_delivery_history`) — `alerts/escalation.py`
  and `routers/alerts.py` no longer reach `query_engine._conn`; the DDL
  (`ensure_alert_history_table`) moved to `control_plane/embedded.py` next to
  its webhook sibling, same catalog-DDL-lock discipline.
- **Alert-rule repository** (`config/alerts.yaml`, including mutable runtime
  state — `state`, `fired_at`, `last_escalation_level`, flap window, cooldown)
  moved behind the port (`load_alert_rules` / `save_alert_rules`); the
  embedded adapter keeps the exact YAML file format, so `config/alerts.yaml`
  is unchanged on disk. `create_alert` / `list_alerts` / `get_alert` /
  `update_alert` / `deactivate_alert` now take the FastAPI `app` (resolving
  the store internally) instead of a bare config `Path`.
- `src/serving/api/alerts/history.py` removed — its logic split between the
  store port (history log) and `alerts/dispatcher.py` (rule repository
  callers); the `get_alert_history` / `ensure_alert_history_table` backwards-
  compatible re-exports on `alert_dispatcher.py` are retired with it (both
  were internal DB-plumbing, not public SDK surface).
- Structural ratchet test extended to `alerts/dispatcher.py`,
  `alerts/escalation.py` and `routers/alerts.py` — none may reach
  `query_engine._conn` directly. New `tests/unit/test_control_plane_store.py`
  coverage for the alert history log and the YAML rule-repository round-trip.

### Added — ControlPlaneStore port + embedded adapter: webhook queue/log behind it (ADR 0010 slice 1, 2026-07-02)

- **New `src/serving/control_plane/`** — the `ControlPlaneStore` port and its
  `EmbeddedControlPlaneStore` (DuckDB) adapter; the webhook durable delivery
  queue and the delivery attempt log are the first subsystem behind it. Pure
  extraction: DDL, SQL shapes, the catalog-DDL-lock discipline and the
  dispatcher's pinned method signatures are byte-compatible — no behavior
  change on the embedded (default) profile.
- Claim semantics are part of the port contract (enqueue-winner-only inline
  delivery; `claim_due` ownership — degenerate in one process, `FOR UPDATE
  SKIP LOCKED` + lease in the slice-5 PostgreSQL adapter); the outcome state
  machine moved into the store so it can be one transaction on PostgreSQL,
  while retry policy stays dispatcher configuration.
- `webhook_dispatcher` and `routers/webhooks.py` no longer reach into
  `query_engine._conn` — pinned by a structural ratchet test; the
  `AGENTFLOW_CONTROLPLANE_STORE` knob resolves the adapter (`postgres` raises
  until slice 5 ships — fail-closed, pinned by test; unknown values fail the
  boot). New `tests/unit/test_control_plane_store.py` (12 tests).

### Added — Control-plane externalization decided; scaling gate enforced at render time (ADR 0010, 2026-07-02)

- **New [ADR 0010](docs/decisions/0010-control-plane-externalization-postgres.md)**
  resolves the choice ADR 0009 deferred: control-plane state (webhook delivery
  queue + attempt log, alert rules **and their mutable runtime state**, alert
  history, replay outbox + dead-letter transitions, usage/session accounting,
  webhook registrations) externalizes to **PostgreSQL behind a
  `ControlPlaneStore` port**, with the embedded DuckDB+YAML store remaining
  the default zero-dependency single-replica profile. Claims are
  `FOR UPDATE SKIP LOCKED` + lease (work-stealing, no leader election), the
  outbox↔dead-letter transactional invariant is preserved natively, and the
  rollout is staged (port extraction per subsystem → PG adapter with live
  verification → Helm wiring → cutover Phase 3). The ADR also extends
  ADR 0009's inventory: webhook registrations and alert rules/runtime state
  live in per-pod YAML files — the sharpest replica split-brain of all.
- **The scaling gate is now enforced, not commented**:
  `helm/agentflow/templates/deployment.yaml` fails **any** multi-replica
  render (`replicaCount > 1`, or autoscaling enabled with `maxReplicas > 1`)
  unless `controlPlane.store=postgres` **and** `serving.backend=clickhouse` —
  previously, disabling persistence let a split-brain multi-replica render
  through. `values.schema.json` pins `controlPlane.store` to the enum
  `["embedded"]` as a fail-closed ratchet until the postgres adapter ships.
  Contract tests pin the gate, the ratchet, and the untouched single-replica
  default (`tests/unit/test_helm_values_contract.py`).
- Cutover plan Phase 3 rewritten with the full prerequisite chain (ADR 0010
  slices) and replica-correctness verification checks (exactly-one delivery
  per (webhook, event) across two pods, one alert page per incident,
  cross-pod webhook registration visibility).

### Added — PostgreSQL port of the vault PII governance (ADR 0006 Phase 2 follow-up, executed 2026-07-02)

- **New `warehouse/agentflow/dv2/postgres/governance/`** — the documented
  follow-up from the ClickHouse governance layer, now shipped: the same PII
  boundary (fail-closed allow-list for `dv2_analyst`, per-jurisdiction
  `dv2_pii_officer__<branch>` roles, jurisdiction row scoping on
  `rv.hub_customer`) translated to PostgreSQL semantics — column grants,
  `ENABLE ROW LEVEL SECURITY` (never `FORCE`: the owner-executed MDM views
  are the `SQL SECURITY DEFINER` analog), and an analyst catch-all policy
  that is deliberately not `TO PUBLIC` (permissive policies OR together and
  would void the officer scoping). PostgreSQL RLS is default-deny for
  unaddressed principals — fail-closed, verified live with a grant-only
  probe user.
- **Verified live** against standalone PostgreSQL 17.5 (33/33 adversarial
  probes, `docs/perf/vault-pii-governance-pg-verify-2026-07-02.md`): every
  PII shape denied for `dv2_analyst`, including whole-row refs, `to_jsonb`
  and positional rename-lists — shapes ClickHouse cannot even express;
  officers row-scoped on the hub across three record_source conventions;
  all four files re-apply idempotently. The ClickHouse filter-pushdown
  ergonomic limitation does not exist on PostgreSQL.
- **New `tests/unit/test_dv2_postgres_governance_ddl.py`** — structural pins
  incl. the fail-closed satellite classification ratchet, the
  no-`TO PUBLIC`/no-`FORCE` policy invariants and the nested-block-comment
  gotcha caught during the live apply; postgres governance DDL is also
  covered by the sqlglot parse + ClickHouse-token-leak sweeps in
  `test_dv2_postgres_ddl.py`.

## [1.6.0] - 2026-07-02

### Added — vault-side PII governance on the engine (ADR 0006 Phase 2, executed 2026-07-02)

- **New `warehouse/agentflow/dv2/governance/`** — ClickHouse RBAC as the PII
  boundary for the DV2 vault, replacing the removed app-level string-parse
  gate with access control on resolved columns: `dv2_analyst` (cross-branch
  analytics, fail-closed allow-list, contact-PII columns never granted) and
  per-jurisdiction `dv2_pii_officer__<branch>` roles (own branch's
  `bv_customer_mdm` view + personal satellite only), plus row policies
  scoping the shared `rv.hub_customer` to the officer's jurisdiction (with
  the mandatory catch-all keeping non-officer visibility independent of
  `users_without_row_policies_can_read_rows`).
- **`bv_customer_mdm__*` views run `SQL SECURITY DEFINER`** so column-limited
  grants on the views work without exposing the underlying
  `sat_customer_personal__1c__*` satellites to readers.
- **`marts.customer_360` is PII-free by contract** — the cross-branch
  materialized mart no longer selects `first_name`/`last_name`/`email`
  (copying jurisdiction-bound PII past the column grants at build time);
  `pii_source` metadata stays.
- **Verified live** against ClickHouse 26.7 (32/32 adversarial probes): every
  PII shape denied for `dv2_analyst` — including the three historical
  bypass forms of the removed app gate, two of which are not even expressible
  on this engine — officers bounded to their jurisdiction, admin unaffected,
  re-apply idempotent. Includes a root-caused ergonomic limitation of filter
  pushdown over column-limited DEFINER views and its PII-safe subquery
  workaround. Evidence: `docs/perf/vault-pii-governance-verify-2026-07-02.md`.
- `infrastructure/dv2/clickhouse-sts.yaml` sets
  `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"` so the stand admin can apply
  RBAC DDL; `tests/unit/test_dv2_governance_ddl.py` pins the boundary
  structure (PII columns never granted, every satellite classified, catch-all
  in sync with officer roles, DEFINER on the views, mart stays PII-free).

### Changed — ClickHouse is the shipped serving engine (ADR 0006 Phase 1, executed 2026-07-02)

- **`config/serving.yaml` defaults to `backend: clickhouse`.** `make demo`,
  `docker-compose.yml`, and `docker-compose.prod.yml` bring the ClickHouse
  service up by default (the `--profile clickhouse` gate is removed; the API
  container `depends_on` its healthcheck). Rollback is config-only
  (`SERVING_BACKEND=duckdb`). Tests stay pinned to DuckDB
  (`tests/conftest.py`), and DuckDB remains the local-dev / test store.
- **The local pipeline writes the serving store** — new
  `src/processing/clickhouse_sink.py`: when the configured backend is
  ClickHouse, every validated event mirrors its serving-table writes and its
  `pipeline_events` journal row there (dead-letter rows included), after the
  DuckDB commit. A configured-but-unreachable ClickHouse fails loudly instead
  of letting the demo serve a frozen seed.
- **Upserts are ReplacingMergeTree row versions.** The four mutable serving
  tables move from `MergeTree` to `ReplacingMergeTree` versioned by a
  `MATERIALIZED af_updated_at` column (invisible to `SELECT *`, inserts, and
  `table_columns`); every backend read carries the `final=1` setting so
  queries always see the latest version. **Existing demo ClickHouse volumes
  must be dropped and re-seeded** (engine changes don't apply to existing
  tables; the demo store is disposable by design).
- **The freshness-critical event scan goes through the serving backend.** New
  `QueryEngine.fetch_pipeline_events()`; the webhook dispatcher (which also
  drives metric-cache invalidation) and the `/v1/stream/events` SSE scan
  delegate to it instead of reaching into the embedded DuckDB connection — so
  event-driven freshness works when the writer is out-of-process and the
  engine is external. Verified live against a real ClickHouse 26.7 server:
  cross-process burst moved the served revenue metric, SSE streamed
  ClickHouse-only events, upsert dedup read back one latest-version row
  (`docs/perf/clickhouse-serving-verify-2026-07-02.md`).
- **Transpile safety net:** `ClickHouseBackend._translate_sql` now fails
  closed if any table reference — including the tenant schema qualifier
  applied by `_scope_sql` *before* the rewrite — does not survive the
  duckdb→clickhouse transpile or does not re-parse. Guards the
  rewrite-after-guard seam that produced the historical PII bypasses, now for
  tenant isolation.
- **Fixed (found by the live verification):** the ClickHouse backend sent the
  session-database URL parameter on the `CREATE DATABASE` bootstrap statement,
  which fails with `UNKNOWN_DATABASE` on a bare server (Docker's
  `CLICKHOUSE_DB` pre-creation masked it).
- **Helm:** new `serving.*` values wire `SERVING_BACKEND` /
  `CLICKHOUSE_*` env (password via `existingSecret`); the chart default stays
  the safe single-node DuckDB profile because the chart ships no ClickHouse
  service. **ADR 0009** records the honest scaling gate: the control plane
  (webhook queue, alert history, outbox, usage) is an embedded per-pod DuckDB
  store, so `replicaCount`/`autoscaling` stay pinned even on the ClickHouse
  profile until it is externalized.

### Removed

- **The serving-layer PII protection is removed — it guarded columns that do not
  exist.** The demo serving warehouse holds no PII: `users_enriched` and
  `orders_v2` (and every other serving table) carry only analytics columns
  (aggregates, ids, timestamps) — none of the fields declared in the former
  `config/pii_fields.yaml` (`email`, `phone`, `full_name`, `ip_address`,
  `shipping_address`) exist in the catalog entity contracts or the physical DDL.
  So the interim NL→SQL `assert_no_pii_access` deny-gate and the entity-path
  `redact_entity` masker were operating on a surface that is never present in the
  demo — defense-in-depth over an empty set. Both are deleted, along with
  `src/serving/pii_policy.py`, `config/pii_fields.yaml`, their CI coverage /
  mutation gates, the helm `piiFields` config, and the `X-PII-Masked` emission
  (the versioned header stays reserved; the generic version-transform that would
  strip it for older clients is unchanged). This also un-breaks the rule-based
  `SELECT *` user/order lookups the deny-gate had been rejecting. The earlier
  SQL-lineage masker (`src/serving/masking.py`, removed in the same cycle) is
  likewise gone. **Real contact PII lives only in the DV2 business vault**
  (`warehouse/agentflow/dv2/business_vault/bv_customer_mdm__*.sql`), and its
  governance belongs engine-side there — ClickHouse row/column policies, tracked
  as ADR 0006 Phase 2 — not in a dialect-pinned string parse in the serving tier.

### Changed

- **NL→SQL LLM path now routes through the GraceKelly orchestration API**
  (`nl_engine._llm_translate`), not a direct provider SDK. It POSTs to
  `${GRACEKELLY_URL}/api/v1/orchestrate` with the target model
  (`GRACEKELLY_NL_SQL_MODEL`, default `claude-sonnet-5`); GraceKelly owns model
  execution (browser-backed). LLM mode is gated on `GRACEKELLY_URL` (was
  `ANTHROPIC_API_KEY`); engine detection across the query package, analytics, and
  agent-query telemetry was realigned to match. The previous direct
  `claude-sonnet-4-20250514` call is removed. The shipped demo still runs the
  **rule-based** translator (GraceKelly is opt-in, unset in deploy configs);
  when configured, GraceKelly serves `claude-sonnet-5`.
- **Serving engine decision: fixed on ClickHouse** (ADR 0006 + 0007). The demo
  serving default moves DuckDB → ClickHouse, with DuckDB demoted to the
  local-dev / test and compatibility store. This unblocks engine-native bounded
  PII (ClickHouse row/column policies) and real Kubernetes horizontal API
  scaling. Recorded as a decision and staged in `docs/clickhouse-cutover-plan.md`;
  the config/compose/Helm cutover itself is **not yet executed**.

### Added

- **DV2 raw vault migrated from ClickHouse to PostgreSQL** with a cloud
  supplier / product reference (`warehouse/agentflow/dv2/`). Hubs, links, and
  satellites are emitted in a PostgreSQL dialect (`argMax` → `DISTINCT ON`,
  `splitByString` → `split_part`); both ingestion feeds (the X5 loader and the
  reference loader) repoint to a shared, parameterized `pg_vault_writer`; and
  OLTP → vault promotion runs as an in-database `INSERT … SELECT` now that OLTP
  and the vault share one engine. The ClickHouse dialect regenerates
  byte-for-byte and is retained for optional mart-serving. Each generated
  `INSERT` is parsed by `sqlglot` in `tests/unit/test_dv2_postgres_ingestion.py`
  to assert every interpolated column exists in the committed DDL. (#91)
- **PyIceberg sink backed by a real MinIO object store** — the REST catalog
  now writes through `S3FileIO` to `s3://agentflow-lake/warehouse` (the same
  bucket the Flink path uses) instead of an ephemeral `/tmp/warehouse`
  `HadoopFileIO`. A self-contained `docker-compose.iceberg.yml` (MinIO +
  bucket-init + REST catalog) and env-overridable credentials in
  `config/iceberg.yaml` make the local catalog object-store-backed; a no-Docker
  guard asserts an `s3://` warehouse never triggers a local `mkdir`. (#92)
- **Event-driven OLTP → vault freshness via PostgreSQL `LISTEN`/`NOTIFY`** —
  `AFTER INSERT/UPDATE` triggers on each `ops_<branch>` table emit
  `pg_notify('dv2_vault_refresh', …)`, and a guarded listener runs an
  idempotent promote on each event (push, not polling), the PostgreSQL
  equivalent of the ClickHouse `MaterializedPostgreSQL` CDC path. Lag is
  observed on the server clock (`db_now`) to stay free of host/container
  clock skew. The driver-agnostic core is covered no-Docker by
  `tests/unit/test_dv2_freshness_listen_notify.py`. (#93)
- OpenSSF Scorecard $0 supply-chain security posture channel:
  `.github/workflows/scorecard.yml` (`ossf/scorecard-action@v2.4.3`) runs on
  push to `main`, weekly, and on branch-protection changes with top-level
  `read-all` permissions and a least-privilege analysis job
  (`security-events`/`id-token` writes only), publishes the public Scorecard
  result, and uploads SARIF to Code scanning. Shape-pinned by
  `tests/unit/test_scorecard_workflow.py`. A companion
  `docs/operations/openssf-security-posture.md` documents the channel and
  carries a prepared OpenSSF Best Practices self-assessment for operator
  submission. These are posture signals only — explicitly NOT a third-party
  penetration-test attestation; backlog item 22 stays N/A and unclaimed.
- Backlog item 19 reopened with a real evidence channel: the production
  source is the operator-owned Neon Postgres backing VacancyRadar
  (`public.vacancies`), recorded with an honest solo-org decision record in
  `docs/operations/cdc-production-onboarding.md`. New dispatch-only
  `.github/workflows/cdc-production-capture.yml` builds the repo's Debezium
  Kafka Connect image, reads connection material only from Actions secrets
  via FileConfigProvider, snapshots the approved table scope over TLS, writes
  an evidence artifact, and always tears down the connector, publication, and
  replication slot (shape tests pin dispatch-only, secret sourcing, sslmode,
  the teardown trap, and always-upload). The first run waits on the operator
  enabling Logical Replication on the Neon project (irreversible
  `wal_level` flip).
- Backlog item 21 closed with real evidence under an operator-amended
  hardware class: `.github/workflows/benchmark-arm.yml` (dispatch-only) runs
  the canonical benchmark on the free GitHub-hosted arm64 runner for public
  repositories (`ubuntu-24.04-arm`, Neoverse-N2, 4 vCPU). First real run
  (27012731848) recorded 554 requests / 0 failures, aggregate p50 6 ms /
  p99 150 ms — every entity gate passed. Evidence in
  `docs/perf/arm-server-benchmark-2026-06-05.md` plus raw artifacts; shape
  tests pin dispatch-only/runner-label/artifact upload, and the job carries
  an A06 dependency-profile target (`perf`). No `c8g.4xlarge` claim is made.

### Changed

- Dependency maintenance batch (consolidated from eight Dependabot PRs): the
  Docker `python` base digest, `cp-kafka-connect-base` 7.9.7 → 7.9.8,
  `apache-flink` 2.2.1 → 2.3.0 (validated by the Flink smoke job), and the SDK
  `vitest` / `schemathesis` bumps, plus the GitHub Pages action major bumps
  (`checkout` v7, `configure-pages` v6, `upload-pages-artifact` v5,
  `deploy-pages` v5) — all SHA-pinned and validated on `main` by the Deploy
  Pages and Flink Smoke runs. (#94)
- Production CDC onboarding, PMF/pricing evidence, a production-hardware
  benchmark, and an external pen-test attestation are documented as out of
  scope for the current plan. Their acceptance criteria require external
  counterparties (production source owners, real customers, production-grade
  hardware, a third-party tester) that are deliberate non-goals for this
  reference project. The gated claims remain explicitly unmade: production CDC
  is not enabled, PMF/pricing is not validated, no production-hardware results
  exist, and no third-party attestation exists. Status is summarized in
  `docs/release-readiness.md`.

### Security

- First OpenSSF Scorecard cycle acted on — published score **5.8 → 7.0**,
  open Code-scanning findings **163 → 53**, every remainder classified
  accepted-open (see `docs/operations/openssf-security-posture.md` §4 for the
  fixed/accepted-open split):
  - Every `uses:` in all 19 workflows (99 references, 20 unique actions) is
    pinned to a full commit SHA with a trailing `# <version>` comment that
    Dependabot's `github-actions` ecosystem keeps updating. The convention is
    enforced by the new `tests/unit/test_workflow_action_pinning.py`;
    per-workflow shape tests now assert action identity (prefix) instead of
    mutable tags.
  - Top-level `permissions: contents: read` added to the five workflows that
    ran on the default token (`staging-deploy`, `e2e`, `contract`,
    `cdc-production-capture`, `benchmark-arm`), and
    `container-attestation.yml` no longer grants
    `packages`/`id-token`/`attestations` writes at the top level — they moved
    to the two operator-dispatched signing jobs, so the every-PR `build-smoke`
    job runs read-only (pinned by a new shape test).
  - All four Dockerfile `FROM` lines are digest-pinned to their current
    manifest-list digests, and the Dependabot `docker` ecosystem now covers
    every Dockerfile directory (`directories:` list) so the pins keep moving
    with upstream tags.
  - `warehouse/agentflow/dv2/loaders/x5_retail_hero/requirements.txt` floors
    raised: `pydantic>=2.9` (GHSA-mr82-8j83-vxmv ReDoS range started at the
    old 2.0 floor) and `tqdm>=4.66.3` (PYSEC-2017-74 and the 2024 CLI
    injection both fall below it). Resolution-floor fixes only; runtime code
    is unchanged.

## [1.5.0] - 2026-06-05

### Added

- **M-C4 closed — argon2id key hashing with an O(1) peppered lookup index.**
  New API-key material is hashed with argon2id (OWASP m=19 MiB, t=2, p=1)
  and stored alongside a deterministic `key_lookup` digest (HMAC-SHA256 of
  the plaintext, pepper from `AGENTFLOW_KEY_LOOKUP_PEPPER`, default
  `agentflow-key-lookup-v1`). `AuthManager.authenticate()` resolves the
  candidate entry via the digest in O(1) and runs exactly one slow verify;
  unknown keys miss the index and pay no slow verify at all. Measured against
  the 2026-05-26 bcrypt baseline on the same hardware class: N=20 hit-last
  cold ≈ 8.1 s → ≈ 34 ms, miss ≈ 8.2 s → ≈ 0.1 ms (the distinct-bogus-key
  DoS amplification is gone). Legacy bcrypt entries keep verifying through
  the old O(n) fallback scan; `create_key`/`rotate_key` write argon2id +
  lookup digests (rotation also carries `previous_key_lookup` through the
  grace window), and the `hashed_key_count_exceeds_guidance` soft-limit
  warning now counts only unindexed legacy entries. The demo
  `config/api_keys.yaml` entries are indexed; `config/security.yaml`
  defaults `key_hashing` to `argon2id` (`bcrypt` remains selectable).
  New dependency: `argon2-cffi`.

### Fixed

- `tests/unit/test_auth_hashed_key_guidance.py` was order-dependent: it
  passed under `pytest tests/unit` but failed in a full-repo run. Any earlier
  test importing `src.serving.api.main` executes the module-level
  `configure_logging()` (`cache_logger_on_first_use=True`), and the first
  emit through the module-level auth logger freezes the production processor
  chain onto the lazy proxy — `structlog.testing.capture_logs()` then cannot
  observe the `hashed_key_count_exceeds_guidance` warning (the warning still
  emits; only the capture goes blind). An autouse fixture now re-points the
  package logger at a fresh uncached proxy per test, making the file
  order-independent. Found while reproducing the 2026-06-03 audit F-1
  claim that the broad no-Docker full-repo pytest run is unreliable on this
  host: on the canonical `.venv` the run completes with a normal summary and
  leaves no orphan uvicorn child (the audit ran the shadow system Python),
  and this order dependence was the only real defect it surfaced.

- The `explain()` sqlglot-failure fallback regex in
  `src/serving/semantic_layer/query/nl_queries.py` contained a literal 0x08
  (backspace) byte where the author meant the two-character escape `\b`: the
  pattern then required a backspace character before `FROM`/`JOIN`, never
  matched, and the fallback silently returned an empty `tables_accessed`
  (which also suppressed the full-table-scan warning). Same corruption family
  as the mojibake box-drawing regex fixed earlier. The control byte is now a
  real word-boundary escape, and a new
  `test_query_package_sources_have_no_control_bytes` fails on any ASCII
  control byte (other than line endings) anywhere in the query package
  sources.
- `[tool.mutmut].paths_to_mutate` pointed at
  `src/serving/semantic_layer/query_engine.py` — a 5-line re-export shim left
  behind by the query-engine package split — so local mutation runs over the
  query surface mutated nothing real (the semantic flavor of the H-2 `auth.py`
  path rot: the file exists, so the existence policy test passed). It now
  targets the five substantive modules in `src/serving/semantic_layer/query/`
  (engine, entity_queries, metric_queries, nl_queries, sql_builder);
  `nl_queries` (the only `validate_nl_sql()` enforcement boundary) and
  `sql_builder` (every entity/metric SQL string) joined the required
  security-critical target set, and a new
  `test_mutmut_targets_define_real_logic` AST policy check fails on any future
  pure re-export target.
- The NL→SQL guard (`validate_nl_sql`) now rejects DuckDB scan functions that
  `sqlglot` parses into typed `Func` nodes. `read_csv` / `read_parquet` parse to
  `exp.ReadCSV` / `exp.ReadParquet`, not `exp.Anonymous`, so the
  forbidden-function check — which only inspected `exp.Anonymous` — missed them
  in projection position: `SELECT read_csv('/etc/passwd') AS v` and the
  `read_parquet` equivalent passed validation untouched (the `FROM`-clause form
  was already caught as a table-valued function). That was an NL→SQL guard
  bypass enabling arbitrary local-file / remote reads through DuckDB scan
  functions. The check now inspects the call name on every `exp.Func` node
  (`.name` for `exp.Anonymous`, `.sql_name()` for typed funcs), so the denylist
  is parser-shape-agnostic and survives `sqlglot` promoting more scan functions
  to typed nodes. Covered by two new projection-position cases in
  `tests/unit/test_sql_guard.py`.
- `[tool.mutmut].paths_to_mutate` pointed at `src/serving/api/auth.py`, which no
  longer exists (auth was split into the `auth/` package), so the mutation gate
  silently mutated nothing for the auth surface. It now targets
  `auth/manager.py` and `auth/key_rotation.py`, restoring mutation coverage of
  the key / verify / rotation paths.
- `[tool.mutmut].paths_to_mutate` now also includes
  `src/serving/semantic_layer/sql_guard.py`, the security-critical NL→SQL
  denylist where the H-6 projection-position bypass lived — a surviving mutant
  in its forbidden-node / forbidden-function checks is a guard bypass, so it is
  the most valuable module to mutate and pairs with its 100% coverage pin. A new
  `tests/unit/test_mutmut_policy.py` asserts every configured mutation target
  still exists on disk (the H-2 failure mode, where a path rotted to the deleted
  `auth.py` and silently mutated nothing) and that the security-critical set
  (sql_guard, auth manager / key rotation, masking, rate limiter) stays listed.
- The daily batch DAG's `daily_product_metrics` and `daily_quality_report`
  assets no longer assume `DuckDBPyConnection.fetchone()` returns a row.
  `fetchone()` is typed `tuple[Any, ...] | None`; the previously untyped
  `COUNT(*)` lookups indexed `[0]` on a possibly-`None` result, which would
  raise if the query returned no row. They now fall back to `0`. Surfaced by
  promoting `src.orchestration.dags.*` to a strict mypy slice; covered by new
  tests in `tests/unit/test_daily_batch_dag.py`.
- `FreshnessMonitor._process_message` no longer crashes on a tombstone /
  payload-less Kafka record. `confluent_kafka.Message.value()` is
  `bytes | None` and `.topic()` is `str | None`; the previously untyped
  handler called `.decode()` on a possibly-`None` body and used a
  possibly-`None` topic as a `dict` key / metric label. It now skips such
  records with a `reason="empty_message"` warning. Surfaced by promoting
  `src.quality.monitors.*` to a strict mypy slice; covered by two new
  tests in `tests/unit/test_freshness_monitor.py` (100% module coverage).

### Changed

- `scripts/` is now part of the CI Ruff gate (2026-06-03 audit F-2:
  release/benchmark/backup/security tooling had drifted to 20 lint errors and
  12 unformatted files that CI never checked). The 12 drifted scripts were
  reformatted (no semantic changes), import order and `datetime.UTC` usages
  auto-fixed, the two >100-char strings in `run_benchmark.py` split, and
  `pyproject.toml` gained a `scripts/**` per-file-ignore for the intentional
  script idioms only — E402 (`sys.path` bootstrap before imports) and
  S603/S607 (fixed-argv `git`/`npm`/`mutmut` subprocess calls), mirroring the
  existing `tests/**` allowance. The `lint` job runs `ruff check` and
  `ruff format --check` over `src/ tests/ scripts/`, and the new
  `tests/unit/test_lint_policy.py` pins the widened scope so the gap cannot
  silently reopen.
- The Flink runtime moved from 1.19.1 to 2.2.1 across the whole project:
  the `[flink]` extra (`apache-flink==2.2.1`), the flink_jobs runtime image
  (Flink 2.2.1 dist + `flink-sql-connector-kafka-5.0.0-2.2.jar`, with a new
  build-time `test -e` guard so a renamed s3-fs-hadoop jar fails the build
  instead of leaving a dangling plugin symlink), and the docker-compose
  cluster images (`flink:2.2.1-java17`). The PR #23 wait-for-upstream gate
  has lifted — Maven Central now ships 2.x-suffixed Kafka connector JARs
  (`5.0.0-2.2` pairs with Flink 2.2). `configure_checkpointing` migrated
  off the APIs Flink 2.x removed: `ExternalizedCheckpointCleanup` →
  `ExternalizedCheckpointRetention`, `enable_externalized_checkpoints` →
  `set_externalized_checkpoint_retention`, and
  `CheckpointConfig.set_checkpoint_storage` → `env.configure()` with the
  `execution.checkpointing.dir` option (a plain-dict fallback keeps the
  no-PyFlink test fakes assertable). The compose overlay now appends
  `FLINK_PROPERTIES` to `config.yaml` (Flink 2.x no longer reads
  `flink-conf.yaml` at all), and the base compose uses the canonical 2.x
  keys (`state.backend.type`, `execution.checkpointing.dir`). The
  `sitecustomize` timedelta shim is unchanged — `pyflink.common.time.Time`
  and `Duration` both survive in 2.2. Validated live in a Flink 2.2.1
  container (Lima Docker on the iMac): module imports, the full
  stream-processor graph build (Kafka connector classes from the new JAR),
  the session pipeline with the new checkpoint API against a real
  environment, the TTL shim, and a MiniCluster execute round-trip all
  passed.
- The agent query endpoints (`/query`, `/query/explain`,
  `/entity/{type}/{id}`, `/metrics/{name}`) were thinned (PR #42; audit
  jgec H-4 / mm F-4): three hand-rolled nested `try/except TypeError`
  cascades (~120 duplicated lines) that progressively dropped
  `tenant_id`/`allowed_tables` for older engine signatures became shared
  module-level helpers with pinned semantics (a `TypeError` only triggers
  the next attempt when its message mentions a kwarg of the *current*
  attempt — genuine engine TypeErrors propagate;
  `tests/unit/test_agent_query_kwarg_fallback.py` pins all branches), and
  the copy-pasted `as_of` validation, tenant resolution and entity-cache
  gating moved into `_normalize_as_of`/`_as_of_iso_text`/
  `_resolve_tenant_id`/`_tenant_context_required`. Behaviour-preserving:
  HTTP status mapping, headers, response shapes and the committed OpenAPI
  spec are unchanged (`export_openapi.py --check` green).
- The ClickHouse serving backend now translates DuckDB-flavored
  semantic-layer SQL through a sqlglot parse → AST rewrite → generate
  pipeline instead of the former regex chain (PR #41; closes audit finding
  H-C2 in full — the earlier literal-masking commit was the narrow fix).
  String literals are preserved structurally by the parser, and
  unparseable or multi-statement SQL now fails loudly as
  `BackendExecutionError` instead of reaching the server half-rewritten.
  Two AST rewrites sit on top of the stock duckdb→clickhouse transpile:
  `<agg> FILTER (WHERE c)` becomes the native `countIf`/`sumIf`/`avgIf`/
  `minIf`/`maxIf` combinators (ClickHouse has no FILTER clause), and
  DuckDB `FLOAT` is widened to DOUBLE so ratio metrics keep the backend's
  historical `Float64` semantics (the stock transpile would emit
  `Float32`). Translation scope is now explicit: `execute`/`scalar`/
  `explain` transpile; the native-ClickHouse demo DDL/INSERT seed and
  `DESCRIBE TABLE` bypass translation, and `explain()` transpiles the
  wrapped query before assembling the `EXPLAIN`. The missing piece that
  kept H-C2 open — live-server evidence — is now permanent CI coverage:
  `tests/integration/test_clickhouse_backend_live.py` runs every catalog
  metric template plus seed-value, literal-round-trip, as-of-anchor,
  EXPLAIN and entity-lookup forms against a real
  `clickhouse/clickhouse-server:25.3` service container on the
  test-integration job (gated on `CLICKHOUSE_LIVE_HOST`, skips cleanly
  where no server is configured). Pre-merge the suite was also validated
  against a disposable live ClickHouse 25.3: 13/13 passed with exact
  seed values (`order_count=8`, `error_rate=0.2`).
- `build-smoke` is now a required branch-protection check on `main` (PR #37 +
  a branch-protection contexts update). The container-attestation workflow's
  `pull_request` paths filter moved inside the job: a `changes` step diffs
  against the PR base and only runs buildx + the no-push image build when
  `Dockerfile*` / root `pyproject.toml` / root `requirements.txt` / the
  workflow itself changed; docker-free PRs complete as an instant
  skip-success. This removes the "Expected — waiting for status" hang a
  paths-filtered required check would inflict on non-Docker PRs (the
  `contract` Lessons 1/4 trap) — the reason the promotion was deferred since
  2026-05-30. Both paths were validated live before the flip: the real build
  ran green on PR #37 (workflow touched) and the skip path completed green on
  throwaway PR #38 (empty diff; buildx/build steps skipped). The workflow
  policy test now pins the always-run shape (no `paths:` on `pull_request`,
  conditional build steps, `GITHUB_OUTPUT` gating).
- The `contract` required check itself now also completes on every PR
  (PR #39) — it was the last required context still carrying the
  trigger-level `pull_request` `paths:` filter (the original Lessons 1/4
  trap, latent only because docs-only changes have so far landed as direct
  pushes to `main`, never as PRs). Same recipe as `build-smoke`/PR #37: the
  filter moved inside the job, where a `changes` step diffs against the PR
  base and the suite steps (editable installs, `generate_contracts.py
  --check`, `export_openapi.py --check`, `pytest tests/contract`) run only
  when contract-relevant paths changed; contract-irrelevant PRs complete as
  an instant skip-success. Push / `workflow_dispatch` events always run the
  full suite, and the `push` trigger keeps its trigger-level paths filter
  (pushes are not gated by the required-check expectation, and the filter
  keeps docs-only pushes cheap). Validated live on both paths before
  closing: the real suite ran green on PR #39 itself (workflow touched) and
  the skip path completed green in 5s on throwaway empty-diff PR #40
  (`changes` + skip note `success`, every suite step literally `skipped`;
  closed unmerged). A new `tests/unit/test_contract_workflow.py` pins the
  always-run shape (no `paths:` on `pull_request`, stable `contract` job
  context, `GITHUB_OUTPUT` change detection, conditional suite steps, and
  the preserved push-trigger filter). No required-contexts change was
  needed — `contract` was already required; the hang trap is simply gone.
- The bandit baseline (`.bandit-baseline.json`) is now empty: its single
  accepted finding (B310, the `urlopen` call in
  `src/serving/backends/clickhouse_backend.py`) moved to an inline
  `# nosec B310 - <reason>` at the call site, matching the file's existing
  B608 suppression convention. Baseline entries are keyed by
  `(test_id, filename, line_number)`, so any line shift above the baselined
  call would have re-classified the accepted finding as new and failed
  Security Scan on an unrelated edit. A new policy test
  (`test_bandit_baseline_carries_no_suppressed_findings`) keeps the baseline
  empty, and the existing nosec-reason test covers the new comment.
  (audit mm F-5)
- Added direct unit coverage for the pure, infra-free security logic in
  `src.serving.api.auth.manager` that the integration / e2e auth suites only
  exercised indirectly: `tenant_key_allowed_tables` (tenant table-allowlist
  resolution / isolation), `TenantKey` key-material validation, legacy
  `AGENTFLOW_API_KEYS` env parsing, and the `_matches_key_material` revoke-path
  matcher — none of which had a direct unit test. `tests/unit/test_auth_manager_pure_logic.py`
  pins their behavior so a tenant-isolation or key-matching regression fails at
  the unit layer. (audit jgec H-5 / mm F-3, partial: the auth/masking modules
  stay integration-covered overall, so no unit-only 90% per-module gate was
  added; the global `--cov-fail-under=60` floor still backstops regressions.)
- Added a per-module 90% coverage gate for `src.serving.masking`, the
  security-critical PII masker and a mutmut target, mirroring the existing
  `sql_guard` / `validators` / `freshness_monitor` / `event_producer` gates in
  `ci.yml` and pinned by `tests/unit/test_coverage_policy.py`. New unit tests in
  `tests/unit/test_masking.py` raise the module's own-file coverage from 66% to
  99%, covering `mask_query_results` (single / multiple / unmapped entity types,
  unparseable SQL, no-op rows), the `None` / unknown-strategy / empty-string
  strategy branches, an empty-local-part email, a single-token name, and the
  address masker (numbered street, single-part, non-numbered street). This
  closes the masking half of the earlier "no unit-only 90% per-module gate"
  note (audit mm F-3 / jgec H-5); the auth manager stays integration-covered.
- Added a per-module 90% coverage gate for `src.serving.api.rate_limiter`, the
  security-critical sliding-window rate limiter and a mutmut target, again
  mirroring the existing gates and pinned by `tests/unit/test_coverage_policy.py`.
  The dedicated test file previously exercised only the Redis path; new tests in
  `tests/unit/test_rate_limiter.py` cover the in-memory fail-open fallback (allow
  up to limit, block over limit, sliding-window expiry, zero-limit block),
  raising own-file coverage from 78% to 98% (only the optional `redis.from_url`
  auto-construct line stays uncovered, env-gated on the `redis` package). This
  extends the audit mm F-3 security-module coverage list beyond masking.
- Added a per-module 90% coverage gate for `src.serving.api.auth.manager`, the
  security-critical auth manager (key match/verify, tenant isolation, rate-limit
  and failed-auth windows, rotation-grace) and a mutmut target, run over its
  dedicated unit files and pinned by `tests/unit/test_coverage_policy.py`. New
  pure-logic tests raise the module's coverage across those files from 82% to
  94% (`get_current_tenant_id`, the `__init__` `DUCKDB_PATH` derivation and
  invalid rotation-grace fallback, env-only `_load_config`, in-memory
  `is_rate_limited`, the `check_rate_limit` redis-reports-full secondary window,
  unrestricted `is_entity_allowed`, and `shutdown`); the remaining gap is the
  platform-divergent SIGHUP handler and bcrypt rotation paths the integration /
  e2e auth suites cover. This **completes the audit mm F-3 security-module
  coverage list** — masking, rate limiter, and auth manager now have unit-only
  90% gates alongside the existing `sql_guard` (100%) and `event_producer`
  gates.
- Added a per-module 90% coverage gate for `src.serving.api.auth.key_rotation`,
  the security-critical key-rotation lifecycle (create / rotate / revoke /
  revoke-old, grace-period scheduling and expiry, rotation status, usage-stat
  queries) and a mutmut target. Like the auth manager gate it uses
  `coverage run` + `coverage report --include` (key_rotation imports duckdb, so
  `pytest --cov` trips the `_duckdb._sqltypes` collection break). A new
  dedicated `tests/unit/test_key_rotation.py` raises the module's own-file
  coverage from 58% to 93%, pinning the rotator logic at the unit layer
  alongside the existing HTTP-level `tests/integration/test_rotation.py`. This
  extends the audit security-critical mutmut-target set with a unit-only gate.
- Added a per-module 90% coverage gate for `src.processing.outbox`, the
  at-least-once delivery loop and a mutmut target, via `coverage run` +
  `coverage report --include` (outbox imports duckdb). A new
  `tests/unit/test_outbox_processor.py` raises own-file coverage from 58% to 92%
  with an injected DuckDB connection and a stub / fake `confluent_kafka.Producer`,
  covering pending/entry dispatch, the success / retry / poison-to-failed state
  machine, exponential and Kafka-floor backoff, the mark-sent and schedule-retry
  transactions (dead-letter replayed/failed and rollback-on-failure), payload
  decoding, the producer adapter, and the `run_forever` error loop. The full
  streaming path stays covered by `tests/integration/test_outbox.py`.
- Added a per-package 90% coverage gate for `src/serving/semantic_layer/query`
  (the NL→SQL orchestration surface and, since the mutmut repoint, a
  mutation-target set), via `coverage run` + `coverage report --include` (the
  engine imports duckdb). A new `tests/unit/test_query_package_logic.py` raises
  package coverage from 64% to 97% with the minimal-host pattern: engine
  lifecycle, sql_builder literal quoting / schema validation / tenant
  qualification + caching, metric and entity error mapping plus the
  quoted-literal (non-DuckDB backend) branches, historical entity lookup over
  pipeline events and the table fallback, NL translation failure hints, cursor
  encode/decode and pagination, unsafe-SQL rejection, and the explain engine
  detection / regex fallback paths. The remaining gap is the OTel
  span-recording branches the integration suites cover.
- Dependabot Tier A wave 4 (2026-06-04): `actions/checkout` 4 → 6 (#33),
  `docker/setup-buildx-action` 3 → 4 (#34), `aws-actions/configure-aws-credentials`
  4 → 6 (#35), `schemathesis` 4.20.0 → 4.21.0 (#32), `pandas` `<3` → `<4` dev
  upper bound (#36), `actions/attest-build-provenance` 2 → 4 (#31). The #31
  bump required unpinning the workflow-policy tests from the exact action
  major (`test_container_attestation_workflow.py` now matches the step by
  action-name prefix, so the next major bump needs no manual test edit).
  Resolver smoke (`pip install --dry-run -e ".[dev,cloud,contract]"`) green
  after the wave.
- Strict typing (`disallow_untyped_defs = true`) is now the global mypy default
  for `src/` rather than ~32 per-module opt-in overrides. Every prior strict
  slice had already been promoted, so the overrides were inverted into one
  global default plus a single explicit relaxation for the PyFlink-gated
  `src.processing.flink_jobs.*` package (no PEP-561 stubs; hot-path jobs gated
  on upstream PR #23). A new untyped def in any non-relaxed module now fails
  mypy instead of slipping through a module nobody pinned, closing the
  ~30-override maintenance surface flagged by the 2026-06-03 audit (H-3).
  `tests/unit/test_typing_policy.py` is rewritten to assert the inverted
  invariant (global strict on, `flink_jobs` the sole relaxation, no redundant
  per-module strict overrides). `mypy src` stays clean on 99 files.
- `src.serving.api.alerts.dispatcher` is now a strict mypy slice
  (`disallow_untyped_defs = true`), completing strict typing across
  `src/serving/api`. The gaps were the three FastAPI app boundaries
  (`get_alert_config_path`, `ensure_alert_dispatcher`,
  `AlertDispatcher.__init__`); `ensure_alert_dispatcher` is guarded against
  `no-any-return` from the dynamically typed `app.state` via a typed local
  rather than a `cast`. Pinned by `tests/unit/test_typing_policy.py`;
  `mypy src` stays clean on 99 files.
- `src.serving.api.routers.deadletter` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the operator-facing dead-letter
  recovery API (list / detail / stats / replay / dismiss) fully annotated over
  the same `dead_letter_events` table the `event_replayer` / `outbox` slices
  manage. The gaps were `_conn`'s return (now a `cast` to
  `duckdb.DuckDBPyConnection` since `app.state` is dynamically typed),
  `_decode_payload`'s `payload`, and the five route-handler return types (their
  Pydantic response models). Pinned by `tests/unit/test_typing_policy.py`;
  `mypy src` stays clean on 99 files.
- `src.serving.api.middleware.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`) — the first bounded slice into
  `src/serving/api`. Keeps the per-request observability path (correlation
  logging, HTTP metrics, tracing) fully annotated. The gaps were the two
  middleware-factory return types (`build_correlation_middleware`,
  `build_metrics_middleware`). Pinned by `tests/unit/test_typing_policy.py`;
  `mypy src` stays clean on 99 files.
- `src.processing.outbox` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the transactional outbox
  (at-least-once delivery guarantee) fully annotated. Typing the
  `DuckDBPyConnection | None` handle (nulled in `close()`) is now routed through
  a `_connection` property, so a use-after-close raises a clear
  `RuntimeError("OutboxProcessor connection is closed")` instead of an
  `AttributeError` on `None`. Other gaps annotated: `ensure_outbox_table`'s
  `conn`, `_process_row`'s `row`, `_decode_payload`'s `payload`, and the nested
  Kafka `on_delivery` callback. Covered by the new
  `tests/unit/test_outbox_connection_guard.py` and pinned by
  `tests/unit/test_typing_policy.py`; `mypy src` stays clean on 99 files.
- `src.processing.local_pipeline` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the zero-infra end-to-end demo
  pipeline (generate → validate → enrich → DuckDB) fully annotated. The gaps
  were five missing `-> None` return annotations (`_ensure_tables`,
  `_upsert_order`, `_upsert_product`, `_upsert_session`, `run`). Pinned by
  `tests/unit/test_typing_policy.py`; `mypy src` stays clean on 99 files.
- `src.processing.event_replayer` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the dead-letter replay path (which
  re-emits failed events through the transactional outbox) fully annotated. The
  gaps were four untyped parameters (`ensure_dead_letter_table`'s `conn`,
  `EventReplayer.__init__`'s `conn`, `_decoded_payload`'s `payload`, and the
  nested Kafka `on_delivery` callback). Pinned by
  `tests/unit/test_typing_policy.py`; `mypy src` stays clean on 99 files.
- `src.orchestration.dags.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the daily batch DAG's scheduled
  asset functions fully annotated. The gaps were six missing return-type
  annotations on `_get_conn` and the five Dagster `@asset` functions. Pinned
  by `tests/unit/test_typing_policy.py`; `mypy src` stays clean on 99 files.
- `src.serving.backends.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the SQL-building DuckDB /
  ClickHouse backends (the H-C1 / H-C2 injection-hardening surface) fully
  annotated. The gaps were the two `scalar()` return types, now `-> Any` to
  match the `ServingBackend` ABC. Pinned by `tests/unit/test_typing_policy.py`.
  (`clickhouse_backend.py` is also normalized from its historical CRLF to LF
  so the repo line-endings are consistent.)
- `src.serving.semantic_layer.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the agent-facing catalog /
  NL→SQL / contracts query surface fully annotated. Pinned by
  `tests/unit/test_typing_policy.py`; `mypy src` stays clean on 99 files.
- `src.quality.monitors.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the freshness / SLA /
  pipeline-health observability paths fully annotated. Pinned by
  `tests/unit/test_typing_policy.py`.
- `src.serving.api.auth.*` is now a strict mypy slice
  (`disallow_untyped_defs = true`), keeping the security-critical
  key / rate-limit / audit paths fully annotated. Promoting it required
  one annotation (`AuthManager.__init__`'s `time_source` parameter typed
  as `Callable[[], float]`); `tests/unit/test_typing_policy.py` pins the
  slice and `mypy src` stays clean on 99 files. Follows the same
  per-module strict-typing cadence as `src.quality.validators.*`.
- `AuthManager.load()` now emits a `hashed_key_count_exceeds_guidance`
  warning when more than `HASHED_KEY_SOFT_LIMIT` (10) hashed API keys are
  configured. This turns the previously docs-only M-C4 guidance
  (`docs/runbooks/auth-401-spike.md`) into a runtime signal: past the
  soft limit the cold-cache `authenticate()` worst case (one bcrypt
  verify per hashed key) crosses the 1100 ms POST load gate measured in
  `docs/perf/auth-bench-2026-05-26.md`, and operators now see it in logs
  before the latency cliff bites. Steady-state stays O(1) via the
  plaintext cache; the full hashed-key-lookup rewrite remains deferred
  (needs the bcrypt hash-format swap).
- New module `src/serving/api/auth/usage_table.py` holds
  `ensure_usage_table` / `record_usage` / `usage_by_tenant`, which used
  to live alongside the ASGI middleware in
  `src/serving/api/auth/middleware.py`. Closes audit L-C4
  ("DB utilities don't belong in a middleware file"). Public callers
  go through `AuthManager.*` shim methods unchanged; the only direct
  importer was `tests/unit/test_audit_publisher.py`, repointed to the
  new module. Middleware drops four dead imports (`duckdb`, `time`,
  `pathlib.Path`, `AuthManager`).

### Performance

- The two Flink hot-path findings from the 2026-05 internal audit are closed
  now that the runtime is on 2.2.1 (they were gated on the PR #23 upstream
  wait). M-C3: `ValidateAndEnrich` emits `(event_id, payload)` pairs and the
  dedup `key_by` reads the key from the tuple, dropping the second
  full-JSON parse per event that existed only to extract `event_id`
  (`DeduplicateByEventId` unwraps the payload; sinks and the dead-letter
  side output stay plain strings, dedup key semantics unchanged). M-C2:
  `FlinkSessionAggregator` constructs one `SessionAggregator` per operator
  instance in `open()` instead of one per element, with full-replace
  `restore()` per event so Flink keyed state stays the single source of
  truth and nothing leaks between keys
  (`tests/unit/test_session_aggregation_flink.py` pins construction count,
  the no-leak invariant, and the session-close state round-trip). Validated
  live on a Flink 2.2.1 MiniCluster: the real dedup pipeline (actual
  validators + enrichment) collapsed a duplicated `event_id` from three
  events to two enriched outputs. The JSON-in-MapState layout is
  deliberately unchanged (checkpoint compatible).
- `scripts/perf/auth_bench.py` + `docs/perf/auth-bench-2026-05-26.md`
  — perf-baseline microbench closing two deferred audit findings.
  Measured `authenticate()` worst-case at production `bcrypt_rounds=12`:
  N=5 hit-last p95 = 1.9 s, N=20 hit-last p95 = 8.1 s (exceeds the
  1100 ms POST load gate). M-C4 stays partial-deferred — steady-state
  is already O(1) via the plaintext cache at `manager.py:284-285`;
  the worst case is cold-cache after process restart / SIGHUP reload,
  bounded by a "≤ 10 hashed keys per AuthManager" guidance now
  documented in `docs/runbooks/auth-401-spike.md`. Measured
  `is_rate_limited()` window-trim p95 at the production default
  `rate_limit_rpm=120` window: **6 microseconds**. M-C5 closed —
  ring-buffer rewrite not worth it.

### Dependencies

- Dependabot Tier A wave 3 (session 26): `schemathesis` 4.19.0 → 4.20.0
  (#25, python-minor-patch group), `hashicorp/setup-terraform` 3 → 4
  (#26), `docker/login-action` 3 → 4 (#27), `actions/upload-artifact`
  4 → 7 (#28), `azure/setup-helm` 4.3.0 → 5.0.0 (#29),
  `actions/setup-node` 4 → 6 (#30). For #27 and #28, the version-pin
  assertions in `tests/unit/test_container_attestation_workflow.py`,
  `tests/unit/test_security_workflow.py`, and
  `tests/unit/test_performance_workflows.py` were bumped on the
  dependabot branches before merge so the squashed commits land green
  in one cycle.

### Fixed

- Ruff format catch-up on two test files from the session-23
  H-C1/H-C4 audit closures (`test_duckdb_backend_sql_hardening.py`,
  `test_lifespan_search_resilience.py`) that had line-length forms
  ruff 0.x rejects. Pure cosmetic line-consolidation, no behaviour
  change.

### Added

- API-surface Prometheus instrumentation referenced by
  [`docs/runbooks/api-5xx-spike.md`](docs/runbooks/api-5xx-spike.md) and
  [`docs/runbooks/auth-401-spike.md`](docs/runbooks/auth-401-spike.md):
  - `agentflow_http_requests_total{method,route,status}` counter via a
    new outermost middleware (`src/serving/api/middleware/metrics.py`).
    Route label uses the FastAPI path template; requests rejected by
    earlier middleware (auth, demo guard) report as `route=<unmatched>`
    because the router only populates `scope["route"]` after
    `call_next`.
  - `agentflow_auth_failures_total{reason}` counter wired into both
    `AuthMiddleware` (reasons: `key_file_empty`, `rate_limited`,
    `missing_key`, `invalid_key`) and `require_admin_key` (reasons:
    `rate_limited`, `admin_unconfigured`, `admin_invalid`). Reason
    vocabulary matches the runbook's Detection section.
  - Sibling Grafana dashboard
    `infrastructure/observability/grafana/agentflow-api-health.json`
    with 5 panels: 5xx-rate-by-route, auth-failures-by-reason (stacked),
    4xx-rate-by-route+status, request-rate-by-status-class (stacked),
    auth-failures-cumulative-over-range bar gauge. Same
    `${DS_PROMETHEUS}` datasource template as `agentflow-pipeline-health.json`.
  - 9 new unit tests in `tests/unit/test_api_metrics.py` cover each
    counter branch and the `/metrics` exposure round trip.
- 6 new unit tests in `tests/unit/test_cdc_connector_configs.py`
  exercise `src.ingestion.connectors.{mysql_cdc,postgres_cdc}`
  pure-Python config builders. Closes audit R4: both files
  went from 0% to 100% combined (line+branch) unit coverage; total
  `src.ingestion` rose 82% → ~85%. Tests pin the operational knobs
  the `cdc-lag` runbook depends on (snapshot mode, heartbeat
  interval, custom metric tags) so accidental drift fails the unit
  step instead of surfacing as silent capture gap.

### Changed

- `.github/workflows/contract.yml` now triggers on
  `infrastructure/terraform/**`, `sdk-ts/**`, and `Dockerfile*`
  paths in addition to the existing src/sdk/pyproject/workflows
  set. Closes audit R2 and removes the last remaining
  `--admin merge` workaround from session 18 for changes outside
  the Python tree.
- `.github/workflows/ci.yml` main coverage gate
  (`test-unit / Run unit and property tests with coverage`) now
  passes `--cov-branch` so the existing `--cov-fail-under=60`
  threshold catches conditional-branch regressions as well as
  unexecuted lines. Local baseline measured before the change:
  62% combined (7716 lines / 2010 branches across 510 tests), so
  the 60% floor stays passing with a 2pp cushion. Closes Kimi
  audit R5. The two per-file 90% gates (validators,
  freshness_monitor) intentionally stay line-only.
- `.github/workflows/container-attestation.yml` now runs on
  `pull_request` events that touch `Dockerfile*` / `pyproject.toml`
  / `requirements.txt` / the workflow file itself, via a new
  `build-smoke` job that does `docker/build-push-action@v7` with
  `push: false` + `load: true` + GHA layer cache. The existing
  `build-push-sign-attest` + `attest-and-sign` jobs are gated
  behind `github.event_name == 'workflow_dispatch'` so a PR can
  never accidentally fire the ghcr.io push / cosign sign path.
  Closes audit R6. A new
  `test_container_attestation_workflow_runs_smoke_on_pull_request`
  unit test asserts the trigger paths, the PR-event gate, and
  push/load shape. Local Docker Desktop 29.4.0 smoke verified the
  Dockerfile.api build itself succeeds (910 MB image in 181 s).
- `src.processing.flink_jobs.*` no longer carries
  `ignore_errors = true` in the mypy override. Suppressed only the
  PyFlink-API quirks (`import-untyped`, `no-any-return`,
  `no-untyped-call`) so real bugs are still caught. Three latent
  type errors in `session_aggregation.py` (`from_snapshot` /
  `process_event` passing `dict[str, object]` values straight into
  `int()` / `float()`) fixed with `cast()` at the JSON boundary.
  mypy is now clean on all 98 source files including
  `checkpointing`, `session_aggregation`, `session_aggregator`,
  `stream_processor`. Closes audit R7.

### Fixed

- Prometheus scrape endpoint (`/metrics`) was rejected with 401 by
  `AuthMiddleware` whenever the request landed on the trailing-slash
  variant `/metrics/` that Starlette redirects to from `/metrics`. The
  exempt set in `_is_exempt_path` only matched the bare path; widened
  to cover both `/metrics` and any `/metrics/...` sub-path so scrapes
  succeed without disabling auth.
- `record_usage` in `src/serving/api/auth/middleware.py` no longer
  re-INSERTs an `api_usage` row when `audit_publisher.publish()`
  fails. The DuckDB insert is now retried in isolation; the audit
  publish runs exactly once after a successful insert and a publish
  failure is logged as `audit_publish_failed` instead of re-driving
  the retry loop. Closes audit H-C3. Two regression tests in
  `tests/unit/test_audit_publisher.py` pin the contract:
  `test_record_usage_no_duplicate_insert_when_publish_raises` and
  `test_record_usage_skips_publish_when_all_inserts_fail`.
- The lifespan-time `SearchIndex.rebuild()` call in
  `src/serving/api/main.py` is now wrapped so a catalog/query-engine
  failure during initial index build leaves the API up with a
  warning (`search_index_initial_rebuild_failed`) instead of
  aborting startup. The 60-second periodic rebuilder (which already
  catches its own exceptions) is still scheduled, so the search
  surface can recover without a process restart. Closes audit
  M-C1. Regression test:
  `tests/unit/test_lifespan_search_resilience.py::test_lifespan_survives_search_rebuild_failure`.

### Security

- `ClickHouseBackend._translate_sql` no longer corrupts user data
  embedded in `'...'` SQL string literals. Before each bare-text
  DuckDB→ClickHouse rewrite (the `::FLOAT`, `NOW()`, `COUNT(*)`,
  `TRUE`/`FALSE`, `CAST(... AS FLOAT)` substitutions) all single-quoted
  literals (including `''`-escaped quotes) are masked with sentinel
  placeholders and restored after the rewrites. The `INTERVAL '...'`
  rewrite still runs first against raw SQL so quoted intervals
  continue to collapse. Closes part of audit H-C2 (literal
  corruption vector). Seven regression tests in
  `tests/unit/test_clickhouse_backend.py::TestTranslateSqlLiteralProtection`
  pin the contract against `::FLOAT`, `NOW()`, `COUNT(*)`, `TRUE`,
  `CAST(... AS FLOAT)`, and `''`-escape forms inside literals.
- `ClickHouseBackend` HTTPS targets now validate the server cert
  against the system trust store explicitly via
  `ssl.create_default_context()` plumbed through to `urlopen`. Insecure
  HTTP backends (default for local-compose) omit the context kwarg so
  Python's `http.client` path is unchanged. Closes part of audit
  H-C2 (no explicit HTTPS validation). Two regression tests cover the
  secure (CERT_REQUIRED + check_hostname True) and insecure (`None`
  context) paths.
- `DuckDBBackend.table_columns()` and `DuckDBBackend.explain()` no
  longer splice arbitrary text into their f-string SQL paths. The
  former now matches an `_IDENTIFIER_RE` accepting either a bare
  `identifier` / `schema.identifier` or a double-quoted DuckDB
  identifier (`"name"` / `"schema"."name"` — the form produced by
  `SQLBuilderMixin._quote_identifier` for tenant-scoped tables; CX
  P1-caught regression — quoted forms must pass through or
  `_qualify_table`'s tenant fail-closed check silently breaks). Inside
  double quotes any character is legal except a lone `"`; `""` is the
  DuckDB-escaped form of an embedded quote. Inputs failing both
  alternatives return an empty column set, mirroring the
  `CatalogException` branch so callers see a missing-table signal
  rather than a 500. The latter parses its input through `sqlglot`
  (DuckDB dialect) and rejects multi-statement or non-`SELECT`
  payloads with `BackendExecutionError` before the `EXPLAIN` wrapper
  runs. Closes audit H-C1. 13 new regression tests in
  `tests/unit/test_duckdb_backend_sql_hardening.py` pin both paths
  against an injection corpus (semicolons, comments, UNION,
  numeric-prefix names, dot-pathology, whitespace) plus
  `main.orders` and `"acme"."orders_v2"` legitimate paths.
- Debezium MySQL connector default `database.server.id` is now
  overridable via the `AGENTFLOW_MYSQL_SERVER_ID` env var. Each running
  Debezium instance MUST advertise a unique `server.id` to MySQL — the
  prior hard-coded `223345` would collide on the replication stream the
  moment a second instance came up against the same source. Default
  preserved as `DEFAULT_MYSQL_SERVER_ID = 223345` so existing
  deployments are unchanged. Closes audit L-C2. Regression test
  `test_mysql_server_id_overridable_via_env` covers env override,
  invalid-int fallback, and unset-env fallback.
- `_CONNECT_SECRET_KEY` in `src/ingestion/connectors/{mysql,postgres}_cdc.py`
  is now the literal `"password"` (with `# noqa: S105` documenting that
  it is a property *key name* inside the Kafka Connect
  `FileConfigProvider` `${file:/path:<key>}` syntax, not a credential).
  The previous `"pass" + "word"` concatenation was security through
  obscurity — bytecode collapses the expression and string scanners
  still see the result. Closes audit L-C1.
- Redundant `event_type == prefix` clauses dropped from
  `src/quality/validators/{schema,semantic}_validator.py`. Python's
  `str.startswith(prefix)` already returns True for the exact-equality
  case (`"order.".startswith("order.")`), so the `or event_type == prefix`
  branch could never fire when the prefix was a non-empty string.
  Closes audit L-C3.
- `AuthManager` no longer grows its `_rate_windows`,
  `_failed_auth_windows`, and `_runtime_plaintext_by_hash` dictionaries
  unbounded. A new `_sweep_expired_windows()` helper drops entries
  whose entire window has aged past the configured cutoff and runs (a)
  on every config reload under `_config_lock`, and (b) opportunistically
  on every successful `clear_failed_auth` call (the post-auth hot path
  is cheap and bounds growth between reloads). `load()` also purges
  cached plaintext-by-hash entries for hashes that no longer appear in
  the live `_hashed_keys` list, so a revoked/rotated key's plaintext
  cannot remain pinned in memory across reloads. Closes audit
  H-C4. Regression tests in
  `tests/unit/test_auth_manager_memory_bounds.py` cover the sweep on
  load, the sweep on clear, the plaintext cache purge, and idempotency
  on empty state.

## [1.4.0] - 2026-05-25

Maintenance release. No runtime API changes; bundles documentation,
CI hardening, repo hygiene, type-stub adoption, and Dependabot Tier A
wave 2 dependency bumps that landed in sessions 11–19.

### Documentation

- Curated the README Documentation index as the cold-start entry point,
  grouping the architecture, API reference, on-call runbooks, and security
  audit so the project's published docs are reachable in one hop.

### Fixed

- Dependency resolver clash after the Dependabot merge cascade
  (`#13 schemathesis 4.10 → 4.19` + `#22 pytest <9 → <10`). schemathesis
  4.19 requires `pytest>=9`; `pytest-asyncio>=0.24,<1` capped pytest at
  `<9` so the `contract` extra became unresolvable. Bumped to
  `pytest-asyncio>=0.24,<2` so pytest-asyncio 1.3.0 (which supports
  `pytest>=8.2,<10`) is installable. Same change was queued in
  Dependabot PR #18; landing it directly here unblocks the Contract
  Tests gate immediately.

### Added

- `.github/dependabot.yml` covering seven ecosystems on a Monday 06:00
  Europe/Moscow weekly schedule: pip (root runtime, SDK, integrations),
  npm (`sdk-ts/`), Docker (`Dockerfile.api`), GitHub Actions
  (workflow pins), and Terraform (`infrastructure/terraform/`). Minor
  and patch updates are grouped per ecosystem to keep the PR queue
  reviewable; majors stay individual. `langchain-core`,
  `langchain-text-splitters`, `langsmith`, and `dagster` have explicit
  CVE-driven floors in `pyproject.toml`, so major bumps for those are
  ignored (Dependabot still opens advisory PRs immediately for
  GitHub-reported vulnerabilities regardless of group/interval).
  Commit prefixes match `CONTRIBUTING.md` (`chore(deps,<scope>)`).
- `.editorconfig` at the repo root pinning UTF-8 + LF + trailing-whitespace
  trim across the tree, with per-language overrides (Python 4-space /
  100-col, JS/TS/JSON/YAML/TOML 2-space, Markdown keeps trailing
  whitespace for hard-wrap line breaks, Makefile tabs). Aligns the
  cross-editor behavior with what `ruff format` / `prettier` already
  enforce in CI; aimed at contributors whose editor does not auto-pick
  up `pyproject.toml` / `package.json` formatter config.

### Documentation

- Public-repo hygiene files added: `SECURITY.md` (private vulnerability
  reporting policy, supported-versions table, scope/out-of-scope, 90-day
  coordinated-disclosure default), structured `.github/ISSUE_TEMPLATE/`
  forms (`bug_report.yml`, `feature_request.yml`, `config.yml` that
  disables blank issues and routes reporters to security/runbook links),
  and a `.github/PULL_REQUEST_TEMPLATE.md` with summary / type-of-change
  / testing / checklist sections aligned to `CONTRIBUTING.md`. All
  cross-link to the existing on-call runbooks and CONTRIBUTING guide
  rather than restating their contents.

### Changed

- `sdk/README.md` (the PyPI project page bundled into every published
  wheel) made version-agnostic: dropped the hardcoded `1.1.0 on PyPI`
  line that went stale at every release in favour of a CHANGELOG link
  pinned to `main`. PyPI keeps showing the README from the bundled wheel
  until the next publish, so this fix is forward-looking — future
  releases will not need an SDK README touch-up just to keep the version
  reference current.
- `helm/agentflow` chart aligned to current release line:
  `Chart.yaml` `appVersion` bumped `1.0.0` → `1.3.0`, default
  `values.yaml` `image.tag` bumped `1.1.0` → `1.3.0`, and
  `docs/helm-deployment.md` examples follow. Helm contract tests +
  helm lint pass; operators who pin their own registry/tag via
  `image.repository` / `image.tag` overrides are unaffected.

### Changed

- Dependabot Tier A wave 2 — seven majors merged in session 18 (commits
  `e2a8288 → 2333104`): `mypy <2 → <3` (dev), `hashicorp/aws ~> 5.60 →
  ~> 6.46` (Terraform), `typescript 5.9.3 → 6.0.3` (sdk-ts),
  `actions/github-script v7 → v9` (CI), `actions/download-artifact v4 →
  v8` (CI), `docs/build-push-action v6 → v7` (CI; included a
  `tests/unit/test_container_attestation_workflow.py` pin bump to match
  the new action version), `vitest 3.2.4 → 4.1.7` (sdk-ts dev). Local
  resolver smoke (`pip install --dry-run -e ".[dev,cloud,contract]"`)
  green on each step. Two Dependabot PRs remain intentionally deferred:
  `apache-flink 1.x → 2.x` (pyflink datastream API break in
  `src/processing/flink_jobs/`) and `python:3.11-slim → 3.14-slim`
  (Docker build is not part of CI, ecosystem compat uneven).

### CI

- `contract.yml` `paths:` filter broadened to also trigger on
  `pyproject.toml`, `sdk/pyproject.toml`, and `.github/workflows/**`.
  This closes the session 16-17 "silent deps cascade" gap (a
  `pyproject.toml`-only commit used to leave Contract Tests on the
  previous, stale SHA) and the session 18 "workflow-only PR cannot
  satisfy required contract check" gap (any workflow bump now
  re-validates the contract suite). Terraform, sdk-ts, and Dockerfile
  paths were left out deliberately — the contract suite is python
  schemathesis and does not exercise those paths, so triggering it
  there would burn CI minutes for no signal. For PRs that touch only
  those files, the documented workaround is `gh pr merge --admin
  --squash` after a manual `gh workflow run contract.yml --ref
  <branch>` SUCCESS.
- `dora.yml` now passes `--branch origin/main` to
  `scripts/dora_metrics.py`. Previously the script defaulted to
  `--branch main`, which works on the `push` / `schedule` /
  `workflow_dispatch` events but fails on `pull_request` because
  `actions/checkout` lands in detached HEAD with no local `main`.
  Every Dependabot PR therefore showed `dora-report: FAILURE` as
  triage noise even though the report is not a required check. With
  `origin/main` the ref resolves correctly in all four event
  contexts.

### Repo settings

- Auto-merge and auto-delete-branch-on-merge enabled on
  `brownjuly2003-code/agentflow`. `gh pr merge <N> --auto --squash`
  is now supported, and Dependabot branches are removed
  automatically once their PR squash-merges. The earlier session 18
  flow (admin-merge per PR, manual `--delete-branch` flag) becomes
  unnecessary for the common case where required checks pass on the
  rebased SHA.

### Types

- `types-PyYAML` added to the dev extra. 16
  `# type: ignore[import-untyped]` annotations on `import yaml` lines
  across `src/` retired; the five remaining `# type: ignore[assignment]`
  annotations are on the `yaml = None` fallback line inside the
  optional-pyyaml `try/except ImportError` blocks (PyYAML is currently
  a hard runtime dependency, but the JSON-fallback machinery in
  `webhook_dispatcher.py`, `slo.py`, `alerts/dispatcher.py` etc. is
  intentionally kept available).
- `types-redis` added to the dev extra. Two
  `# type: ignore[import-untyped,unused-ignore]` annotations on
  `import redis.asyncio as redis` retired in `src/serving/cache.py`
  and `src/serving/api/rate_limiter.py`; the `redis = None` fallback
  keeps its `assignment` ignore for the same reason as yaml.
- Net change: total type-ignore count in `src/sdk` dropped 20 → 13,
  with the `import-untyped` category eliminated entirely. `mypy src
  sdk` still clean (0 errors, 105 files).

### Documentation

- README refreshed to `v1.3.0` reality: release-gate badge bumped, the
  Highlights section reflects the `v1.1` → `v1.3` arc and the DV2 demo
  triptych, the Status block summarizes what landed in each of the three
  releases and what external gates remain, and the Documentation index
  now links to `docs/runbooks/` alongside the existing single-page
  `docs/runbook.md` (the singular file remains the local-dev
  quick-reference; the plural directory is the on-call incident
  playbooks).
- On-call production incident runbooks in `docs/runbooks/`: index plus five
  symptom-keyed playbooks (`api-5xx-spike.md`, `auth-401-spike.md`,
  `cdc-lag.md`, `load-test-regression.md`, `release-rollback.md`). Each
  follows the eight-section format (Symptom / Severity / Owner / Detection /
  Triage / Mitigation / Resolution / Postmortem trigger) and references real
  signals already in the codebase: Load Test gates from
  `tests/load/thresholds.py`, the fail-closed auth path from
  `src/serving/api/auth/middleware.py`, the v1.3.0 release surfaces
  (`docs/dv2-multi-branch/RELEASE_STATUS.md`,
  `.github/workflows/publish-pypi.yml`, `.github/workflows/publish-npm.yml`),
  and the production CDC onboarding decision record in
  `docs/operations/cdc-production-onboarding.md`. Severity ladder aligns with
  `docs/operations/chaos-runbook.md` so paging behavior stays consistent
  across all incident types.

## [1.3.0] - 2026-05-24

### Added

- A04 chart hardening: `helm/kafka-connect/` now ships NetworkPolicy +
  PodDisruptionBudget + pod/container securityContext + `/tmp` memory
  emptyDir (parity with `helm/agentflow`). All five primitives are
  required by `values.schema.json` and off-by-default for backwards
  compatibility on existing clusters; production switches them on via
  `values-staging.yaml`-style overlays. See
  `docs/operations/cdc-production-onboarding.md` § Chart hardening
  baseline for the production switch-on recommendations.
- A05 live-validation coverage extended: the
  `tests/integration/test_helm_values_live_validation.py` suite is
  now parametrized across both `helm/agentflow` and `helm/kafka-connect`
  charts, running lint + install --dry-run against the live kind
  cluster with valid + invalid value fixtures each.
- A05 reuse-cluster mode: `conftest.kind_cluster` honours
  `AGENTFLOW_LIVE_REUSE_CLUSTER=1` to skip the kind create/delete cycle
  and validate against an active `KUBECONFIG` context. Lets the
  schema gates run against managed staging clusters (EKS/GKE/AKS)
  without provisioning a throwaway kind cluster.

### Changed

- A03 CI hardware-gap acceptance: Load Test gates raised to 1.3x the
  2026-04-25 CI baseline (entity p99 750 → 900 ms, query/batch
  1000 → 1200 ms). Local SLO p99 < 200 ms unchanged. Decision record
  + alternatives considered: `docs/perf/ci-hardware-gap-2026-05-24.md`.

### Documentation

- DV2 web-UI screencast (`docs/dv2-multi-branch/demo_webui.mp4`,
  ~60 s, 1.6 MB) — Playwright run through Argo workflow archive
  (4× successful `dv2-refresh` runs + DAG drill-in on the latest) and
  the MinIO `cold-tier` bucket browser (5 per-branch prefixes), with
  a Russian TTS voice-over. Reproducer:
  `docs/dv2-multi-branch/demo_webui.capture.py` plus the same
  edge-tts + ffmpeg pipeline as the terminal cast.
- DV2 dbt docs screencast (`docs/dv2-multi-branch/demo_dbt_docs.mp4`,
  ~55 s, 1.7 MB) — Playwright walk-through of the auto-generated dbt
  docs site: project tree → `customer_360` columns/description →
  `branch_pnl` with the `rv.bv_order_canonical → branch_pnl` lineage
  graph → `returns_velocity` with lineage. Companion Pod manifest
  `infrastructure/dv2/dbt/dbt-docs-pod.yaml` runs `dbt docs generate`
  + `dbt docs serve --port 8080 --host 0.0.0.0` against the in-cluster
  ClickHouse. Reproducer: `demo_dbt_docs.capture.py` plus the same
  TTS pipeline.
- Cross-link `docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md`
  to `docs/operations/cdc-production-onboarding.md` (production source
  onboarding still blocked on decision-record fill-in) and note that
  the DV2 demo uses ClickHouse `MaterializedPostgreSQL` as a
  single-node alternative, not a production replacement for
  Debezium/Kafka Connect.
- Exploration archive: `docs/exploration/2026-05/` collects three
  stale May-6/7 docs-site drafts (`astro_prompt.md`, `kimi.md`,
  `research.md`) that had been sitting untracked in the repo root.

### Fixed

- Typed `RetryPolicy.compute_delay()` intermediate `base` in
  `sdk/agentflow/retry.py` so the function no longer returns
  `Any`; SDK mypy is now strict-clean.
- CI / release / packaging lessons-learned document
  (`docs/lessons/ci-repair-sprint-2026-04.md`) — seven concrete
  Lesson / Apply / Concrete-trace entries covering A06 dependency
  profiles, single-run baseline anti-pattern, FastAPI version drift,
  PyPI namespace pre-claim, required-check self-reference deadlock,
  fail-closed auth + `/v1/health` exemption, and the DV2 voice-over
  pipeline.

## [1.2.0] - 2026-05-23

### Documentation

- Documented the demo-key requirement, current DuckDB/ClickHouse serving
  story, Docker Redis dependency for the local demo, example-agent dry-run
  flow, and local compose environment placeholders.
- Refreshed release, SDK, and integrations docs after the live v1.1.0
  registry publish: README status, release-readiness handoff, SDK README,
  integrations local-install note, and the T31 task closeout now match the
  current post-release state.
- Prepared npm publishing for Trusted Publishing through GitHub Actions OIDC:
  the TypeScript SDK publish workflow now requires npm CLI 11.5.1+ and no
  longer passes `NPM_TOKEN` to the production `npm publish` step.
- Recorded the npm Trusted Publishing handoff: the package
  `@yuliaedomskikh/agentflow-client@1.1.0` was first published and Trusted
  Publisher setup succeeded for `brownjuly2003-code/agentflow` with workflow
  `publish-npm.yml`; CLI `npm trust list` readback is complete.
- Switched future TypeScript SDK publishing to the
  `@yuliaedomskikh/agentflow-client` npm scope.
- Clarified that legacy `NPM_TOKEN` revocation remains blocked until a
  successful trusted-publish workflow run for `@yuliaedomskikh/agentflow-client`
  and accepted external-gate intake evidence exist.
- Added a project-local Pi skill at `.pi/skills/external-gate-evidence-intake`
  for external release-gate evidence intake without adding runtime dependencies.
- Added a production CDC onboarding runbook that blocks real source attachment
  until source ownership, table scope, network path, credential ownership,
  monitoring, and rollback decisions are recorded.

### Fixed

- Treated corrupt Redis cache payloads as cache misses instead of surfacing
  JSON decode failures to API requests.
- Fixed TypeScript SDK SSE parsing so a final frame with `id:` or `event:`
  metadata before `data:` is still emitted.
- Made the TypeScript SDK unit-test script include all `sdk-ts/tests` files and
  included `CHANGELOG.md` in the npm dry-run package contents.
- Allowed packaged SDK starter templates to include placeholder
  `.env.example.tmpl` files while keeping the release artifact checker strict
  for real `.env` files, API-key configs, webhook configs, and secret paths.

### Security (audit follow-up sprint 2026-04-27/28)

Two internal security audits were delivered against `4a13d36`. Six commits
closed all P0/P1/P2 findings.

**Tenant isolation across the control plane (audit p1 R3/R5, p2_1 #1-3,
p3 #4):** `pipeline_events` and `dead_letter_events` got a
`tenant_id VARCHAR DEFAULT 'default'` column with backwards-compatible
`ALTER TABLE ADD COLUMN IF NOT EXISTS` migration in init paths. Writers
populate tenant from `event['tenant']` / CDC source metadata; the CDC
normalizer accepts an explicit `topic=` argument and falls back through
`event['topic']` → `cdc.<source.db>` → `source.name`. Readers in
`/v1/stream/events`, `/v1/lineage`, `/v1/slo`, `/v1/deadletter`
(stats / list / detail / replay / dismiss), and the webhook dispatcher
now scope to `request.state.tenant_id`. Cross-tenant regression tests
added.

**SQL guard centralization (audit p2_1 #4, p2_2 #4, p3 #1):** new
`_prepare_nl_sql()` helper in `nl_queries.py` is the only path that
validates translated SQL via `validate_nl_sql()`; called from
`execute_nl_query`, `paginated_query`, and `explain` before tenant
scoping and pagination wrapping. Closes the bypass on `/v1/query`
(paginated) and `/v1/query/explain`. PII masking and explain
`tables_accessed` rewritten on `sqlglot` AST so tenant-quoted SQL like
`"acme"."users_enriched"` is correctly extracted (audit p3 #3).

**Entity allowlist enforcement (audit p2_1 #4, p3 #2):** new
`tenant_key_allowed_tables()` helper in `auth/manager.py`. Applied to
NL query / explain / paginated query, batch query/metric items,
`/v1/search` (intersection with tenant key allowlist + post-filter so
metric documents are not silently dropped for scoped keys), and
`/v1/metrics/{metric}`.

**Auth fail-closed + entropy + scopes (audit p2_1 #5, p2_2 #1-3):**
auth middleware now fails closed with `503` when no API keys are
configured; opt out with `AGENTFLOW_AUTH_DISABLED=true` for local dev
or `app.state.auth_disabled = True` for tests. Failed-auth throttling
extended to `/v1/admin/*`. `X-Forwarded-For` honoured only when the
immediate peer is in `AGENTFLOW_TRUSTED_PROXIES`. Generated API keys
now use `secrets.token_urlsafe(32)` (256-bit) instead of
`secrets.token_hex(4)` (32-bit).

**Secret hygiene (audit p2_2 #5/8, p9 #4-5):** rotated active webhook
signing secret in `config/webhooks.yaml`, replaced tracked plaintext
API keys in `k8s/staging/values-staging.yaml` with placeholders +
`.yaml.example` schema reference, env-driven
`docker-compose.prod.yml` (`${CLICKHOUSE_*:?}`, `${GF_SECURITY_*:?}`),
placeholder passwords with prod warnings in
`helm/kafka-connect/values.yaml`, untracked
`docker/kafka-connect/secrets/{postgres,mysql}.properties` + `.example`
templates. Tight Hatch sdist `include`/`exclude` keeps secrets,
workflows, notebooks, k8s, helm, sdk, integrations, tests, and docs
out of the runtime distribution. `X-Admin-Key`, `Cookie`, and
`Set-Cookie` added to redacted headers. Webhook/alert `secret` excluded
from list/read/update responses (returned only on create). Admin UI
no longer renders `X-Admin-Key` into the DOM (`data-admin-key` and
auto-refresh JS removed). `/v1/admin/keys` no longer returns plaintext
key material.

**Helm hardening (Opus P1 #4-6):** `helm/agentflow/templates/` gained
`networkpolicy.yaml` (default-deny + ingress on the http port + egress
to DNS/Redis/Kafka/ClickHouse/OTLP) and `poddisruptionbudget.yaml`
(`minAvailable: 1`). Pod and container `securityContext` now sets
`runAsNonRoot=10001`, `readOnlyRootFilesystem=true`, drops all
capabilities, and applies `RuntimeDefault` seccomp; a memory `emptyDir`
mounts at `/tmp` for Python tempfile / httpx caches. NetworkPolicy is
off by default (enable per cluster).

**Supply chain (audit p9):** committed `sdk-ts/package-lock.json`
(closes ENOLOCK on `npm audit`); `publish-npm.yml` switched to
`npm ci` + `npm test` + `npm audit` before publish. New `npm-audit` job
added to `security.yml`. `aquasecurity/trivy-action` pinned from
`@master` to `0.28.0`. Safety scope now includes
`integrations/pyproject.toml` resolved requirements. TypeScript SDK npm
publishing now targets `@yuliaedomskikh/agentflow-client` because npm org scope
`@agentflow` is already owned by another project and the previous user scope is
legacy.

**Vulnerable dep bumps:** `dagster>=1.13.1` (GHSA-mjw2-v2hm-wj34
SQL injection via dynamic partition keys), `langchain-core>=1.2.22`
(CVE-2026-26013 SSRF + CVE-2026-34070 path traversal),
`langchain-text-splitters>=1.1.2` (GHSA-fv5p-p927-qmxr SSRF redirect
bypass), `langsmith>=0.7.31`. Both `pyproject.toml` and
`integrations/pyproject.toml`.

**OpenAPI drift gate (audit p4 #5):** `scripts/export_openapi.py`
gained a `--check` mode that diffs the regenerated `docs/openapi.json`
and `docs/agent-tools/*.json` against committed copies. Wired into
`contract.yml`; `docs/agent-tools/**` and `scripts/export_openapi.py`
added to `contract.yml` path triggers.

**Branch protection:** `main` has 12 required status checks
(`lint`, `test-unit`, `test-integration`, `perf-check`,
`helm-schema-live`, `schema-check`, `terraform-validate`,
`bandit`, `safety`, `npm-audit`, `trivy`, `contract`),
`strict=true`, force-pushes and deletions disabled, required
conversation resolution. `record-deployment` was originally part
of this set but its bot push couldn't pre-satisfy the protected
branch gate; the job was removed
and DORA metrics fall back to the GitHub Actions API source
already wired into `scripts/dora_metrics.py`.

**Python SDK alignment with server v1 contract (audit p8 F1–F10):**
`api_version=` parameter and `X-AgentFlow-Version` header on sync and
async clients; capture of server version + deprecation headers into
`client.last_server_version` / `last_deprecation_warning`. Async
contract pinning parity with sync (in-memory contract cache, async
`_get_contract`). `as_of: datetime|str|None` parameter for entity
helpers and `get_metric` (sync + async). New `EntityMeta` and
`MetricMeta` Pydantic models exposed via `EntityEnvelope.meta` and
`MetricResult.meta`. Full `CatalogResponse` payload:
`streaming_sources`, `audit_sources`, plus `contract_version` on
catalog entities and metrics. Eight new public typed methods —
`explain_query`, `search`, `list_contracts`, `get_contract`,
`diff_contracts`, `validate_contract`, `get_lineage`, `get_changelog`.
New public `AgentFlowClient.get_entity()`; existing typed convenience
methods now delegate to it. `_request` accepts a `headers=` argument;
public POSTs accept `idempotency_key=` so retries are permitted on
5xx / timeout. New `PermissionDeniedError(AgentFlowError)` for `403`.
`CircuitOpenError` now inherits from `AgentFlowError`. Both
re-exported from `agentflow.__init__.__all__`. New
`sdk/agentflow/py.typed` marker; Hatch include rule keeps it in the
wheel/sdist.

**Test coverage gaps (audit p5):** new unit suites covering
previously zero-coverage modules — `tests/unit/test_clickhouse_backend.py`
(14 tests: SQL translation, basic-auth POST, UNKNOWN_TABLE mapping,
URLError mapping, table_columns fallbacks, EXPLAIN, scalar, https
switch, health), `tests/unit/test_freshness_monitor.py` (8 tests:
latency / SLA window / breach signalling / skip-reason coverage /
EOF vs real Kafka error / consumer.close), and
`tests/unit/test_event_producer.py` (9 tests: all four generators,
DecimalEncoder, run_producer flush on KeyboardInterrupt,
_delivery_report).

**Test fixture posture:** new autouse
`_default_open_auth` fixture in `tests/integration/conftest.py` keeps
the legacy "open when no keys" behaviour for integration tests that do
not exercise auth (sets `AGENTFLOW_AUTH_DISABLED=true`); opt out with
the new `requires_auth_enforcement` marker.
`app.state.auth_disabled = False` is reset on every lifespan startup
so the test bypass flag does not leak across `TestClient` instances
(closes review P2 on auth/middleware persistence).

**Documentation hygiene (audit p6):** TypeScript SDK examples now
import from `"@yuliaedomskikh/agentflow-client"` (was `"agentflow"`); placeholder
`https://api.agentflow.dev` examples replaced with
`http://localhost:8000`; clone URL points at
`brownjuly2003-code/agentflow`; `docs/quality.md` marked stale;
`docs/glossary.md` test counts and `docs/engineering-standards.md`
coverage floor (`60%`) re-aligned with CI; runbook clarifies that
`make demo` does start Redis via Docker; migration guide module path
fixed (`local_pipeline.run`); registry-not-yet-published wording
through README, integrations, migration, sdk/sdk-ts READMEs.

**Operational verification:** the chaos smoke hang flagged in
`docs/release-readiness.md` did not reproduce on the new HEAD —
`tests/chaos/test_chaos_smoke.py` now passes `3 in 44s` standalone with
`--timeout=60 --timeout-method=thread`. `app.state.auth_disabled` is
reset on lifespan startup so the test bypass flag does not leak across
`TestClient` instances. Final smoke at audit-closure HEAD:
`670 passed, 4 skipped` on
`pytest tests/unit tests/integration tests/sdk tests/contract`.

**Audit closure:** two internal security audits drove the work; their
findings map to the six closing commits.

### Added

- **DV2.0 multi-branch demo** (merged via `ddfb863` from
  `feat/dv2-multi-branch`, sessions 1-5). Live Data Vault 2.0
  warehouse on a self-hosted kind cluster with ClickHouse 25.5,
  Postgres 17, and MinIO. Five branches (MSK / SPB / EKB / DXB / ALA),
  three source systems (1C + Bitrix24 + WMS Excel), three jurisdictions
  (RU / UAE / KZ). Artifacts:
  - `warehouse/agentflow/dv2/raw_vault/` — 8 hubs + 8 links + 39
    satellites (generator + jinja template + spec.yaml).
  - `warehouse/agentflow/dv2/business_vault/` — 5 per-branch MDM views
    plus `bv_order_canonical` with `*_source` audit columns.
  - `infrastructure/dv2/` — kind topology, ClickHouse / Postgres / MinIO
    StatefulSets, dbt mart runner, Argo Workflows installer and
    `dv2-refresh` WorkflowTemplate, cold-offload CronJob fanout (5).
  - `warehouse/agentflow/dv2/postgres_oltp/` — pull-based PostgreSQL()
    bridge + push-based MaterializedPostgreSQL CDC (single-DB pattern).
  - `warehouse/agentflow/dv2/postgres_oltp/fanout/` — per-branch CDC
    fan-out via per-database split (`ops_msk_db`, `ops_dxb_db` →
    `oltp_cdc_msk`, `oltp_cdc_dxb`). Native workaround for the
    `materialized_postgresql_publication_name` setting being unsupported
    in ClickHouse 25.5; PeerDB OSS was the originally-planned route but
    does not fit on the 8 GB demo iMac alongside kind + CH + PG + MinIO.
  - `warehouse/agentflow/dv2/dbt/` — three mart models
    (`customer_360`, `branch_pnl`, `returns_velocity`) with 12 data
    tests and a k8s Job runner.
  - `docs/dv2-multi-branch/` — architecture diagram, demo evidence
    (15 sections), 2-minute pitch script, recording-day runbook,
    asciinema cast (`demo.cast`, 42 s, 130×35) plus runner, plain-text
    transcript, self-contained HTML player embed, and a voice-over
    MP4 (`demo_voiced.mp4`, ~92 s) — cast slowed to match a Russian
    TTS narration of the pitch (reproducible via
    `docs/dv2-multi-branch/build/build_voiced_demo.sh`).
- **Debezium/Kafka Connect CDC operationalization**: local compose now
  brings up Postgres/MySQL source databases, Kafka Connect, Debezium
  connector registration, and raw CDC topic bootstrap for the AgentFlow
  demo schema.
- **Kafka Connect Helm chart**: `helm/kafka-connect/` defines the
  Connect worker deployment, connector registration hooks, secrets,
  values schema, and topic bootstrap job for Kubernetes-shaped staging.
- **Canonical CDC normalizer**: raw Debezium envelopes from Postgres
  and MySQL now normalize into the AgentFlow CDC contract before
  downstream validation and Flink processing.

### Changed

- **Kafka Connect Helm secret contract**: `helm/kafka-connect`
  values now reject ambiguous source-credential settings. Use exactly
  one mode: chart-created demo Secret (`secrets.create=true`) or an
  existing Kubernetes Secret (`secrets.create=false` with
  `secrets.existingSecret`).
- **CDC watermarks**: the Flink CDC path now uses source timestamps
  from normalized Debezium records, keeping event-time behavior aligned
  with source database changes.
- **Performance gate enforcement**: `scripts/check_performance.py`
  now enforces endpoint-level p99 gates instead of only aggregate
  benchmark status.

### Documentation

- `docs/runbook.md` now documents local CDC startup, connector status
  checks, the optional Docker CDC integration test, cleanup, and the
  Kafka Connect Helm source-credential modes.
- `docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md`
  now reflects the implemented local/Helm CDC path, including topic
  bootstrap, schema-history topic behavior, and the explicit Helm
  secret contract.

---

## [1.1.0] - 2026-04-25

See [docs/migration/v1.1.md](docs/migration/v1.1.md) for upgrade instructions from v1.0.x.

### Added

- **MCP integration** for Claude Desktop, Cursor, and Windsurf:
  `integrations/agentflow_integrations/mcp/` ships a Model Context
  Protocol stdio server with `entity_lookup`, `metric_query`,
  `nl_query`, `health_check`, and `list_entities` tools wrapping the
  public `AgentFlowClient`. Install via `pip install -e "./integrations[mcp]"`
  and launch with `python -m agentflow_integrations.mcp`. (07cb253)
- **Entity type registry**: the four core entity types (`order`,
  `user`, `product`, `session`) now load from
  `contracts/entities/*.yaml` instead of being hardcoded inside
  `DataCatalog`. Adding a new entity type is a YAML file plus a
  process restart. (f9e78de)
- **AWS OIDC Terraform module**
  (`infrastructure/terraform/modules/github-oidc/`): IAM OIDC provider
  and branch/environment-scoped IAM role for GitHub Actions Terraform
  runs. `terraform-apply.yml` now reads `vars.AWS_TERRAFORM_ROLE_ARN`
  and uses short-lived credentials exclusively. (f1f6908)
- **Benchmark history** (`.github/perf-history.json`): rolling log of
  `p50/p95/p99/throughput` appended by a `perf-history-bot` commit on
  each `main` push. Plot the trend locally with `make perf-plot`.
  (447440a)
- **Codecov integration**: `codecov.yml` config, tokenless OIDC
  upload in `ci.yml`, README badge, and
  `docs/operations/codecov-setup.md`. (4a02945)
- **Entity profiling harness**: `scripts/profile_entity.py` client
  that hits one entity endpoint at a fixed concurrency and prints
  `p50/p95/p99`. Paired with `docs/perf/README.md` describing the
  py-spy workflow and stack requirements for meaningful numbers.
  (0873c94, 13ad163)
- **Scheduled chaos full suite**: `chaos.yml` now runs the full
  suite daily at `0 4 * * *` plus on `workflow_dispatch`, and files a
  GitHub issue tagged `chaos-failure` / `severity:high` when a
  scheduled run breaks. (4dd27fa)

### Changed

- **Package versions synced to 1.0.1** across `pyproject.toml`,
  `sdk/pyproject.toml`, `sdk/agentflow/__init__.py`, and
  `sdk-ts/package.json`. Pinned with `tests/unit/test_version.py`.
  (5d54b77)
- **Runtime/package identity split**: the root repo now publishes as
  `agentflow-runtime` while the Python SDK publishes as
  `agentflow-client` and keeps the `agentflow` import path and CLI.
  Local test/install flows now install `./sdk` explicitly instead of
  relying on `sys.path` shims or install order.
- **SDK PyPI distribution renamed**: published as `agentflow-client`
  (was planned as `agentflow` in A01, but the name was already taken
  on PyPI by an unrelated abandoned project). Python module and API
  unchanged - `from agentflow import ...` still works. Install with
  `pip install agentflow-client`.
- **`integrations/` package bumped to 1.0.1** with the `mcp`
  optional extra and an `agentflow-mcp` console script; the stale
  SDK dependency now points at the public `agentflow-client>=1.0.1`
  package. (07cb253)
- **28 historical plan docs archived** from `docs/plans/` to
  `docs/plans/codex-archive/`. `docs/plans/` now only holds live
  work. (0e9fc00)

### Documentation

- `docs/operations/aws-oidc-setup.md`, `docs/operations/chaos-runbook.md`,
  `docs/operations/codecov-setup.md`.
- `docs/contracts/how-to-add-entity.md`.
- `docs/perf/README.md` profiling workflow and stack caveat.
- `integrations/agentflow_integrations/mcp/README.md` with Claude
  Desktop config snippet.

### Dependencies

- `pyyaml>=6,<7` added to core dependencies (previously only
  transitively present via dagster/langchain).

### Verification

Test suite status at sprint close: **552 tests passing**, 1 skipped,
0 regressions.

| Suite | Count | Duration |
|-------|-------|----------|
| unit | 360 | ~60 s |
| property + contract + sdk | 38 | ~31 s |
| e2e (non-dagster) | 13 | ~63 s |
| integration (non-Docker) | 141 | ~108 s |

### CI repair trail

Surface-level diagnosis after push surfaced six pre-existing CI
breakages that predate the v1.1 sprint (first observed 2026-04-20):

- **Contract Tests** (`54c3c27`, `2cf7a7b`): root and SDK both declare
  `name = "agentflow"`, so `pip install -e sdk/` uninstalled the root
  package and left `src` unimportable. Dropped the separate SDK install
  and switched to `pip install -e ".[dev,cloud]"` so pyiceberg is
  present when the fixture boots the API.
- **Load Test** (`b2f8344`, `aa470df`): same missing `[cloud]` extras
  blocked uvicorn startup — `Connection refused` on port 8011. Added
  the extras, then bumped `AGENTFLOW_RATE_LIMIT_RPM` to `600000` so
  the 50-user locust workload stops saturating the limiter.
- **Staging Deploy** (`8bedb1d`): the `.gitignore` rule `AgentFlow*`
  swallowed `helm/agentflow/` on case-insensitive filesystems. Added
  `!helm/agentflow/` / `!helm/agentflow/**` exceptions and committed
  the 12-file chart that existed only on dev machines.
- **Security Scan** (`68ca0da`): `aquasecurity/trivy-action@0.33.1`
  was not a real release — switched to `@master` pending a pinned
  version from the user. The resulting Trivy run now reaches the
  scan step but the image has unresolved HIGH/CRITICAL findings that
  still fail the gate (next-session work).
- **CI lint** (`70a7b64`): ran `ruff --fix` against the 27 files with
  auto-fixable debt; 38 of 98 errors cleared. 60 harder lint errors
  (E501, S603, E402, N802, B904) remain — a dedicated cleanup pass
  is still needed before the `lint` job can go green.
- **E2E Tests**: pre-existing `wait_for_services` timeout on the
  docker-compose-hosted API. Not investigated this session — the
  stack uses `docker-compose.prod.yml` which pulls a dozen services;
  the root cause likely overlaps with the rate-limiter / Kafka
  readiness issue and needs hands-on debugging.

Status at session close: **Contract Tests should go green after
`2cf7a7b` lands, Load Test after `aa470df`, Staging Deploy after
`8bedb1d`**. CI lint, Security Scan (Trivy findings), and E2E Tests
still require follow-up.

---

## [1.0.1] - 2026-04-20

Post-publication patches ensuring clean-clone installation works out of the box.

### Fixed

- **SDK sources missing from git tree**: `sdk/agentflow/` and `integrations/agentflow_integrations/` were not tracked, causing ImportError on fresh clones. Now included. (302883e)
- **Cached bytecode in tracked paths**: `.pyc` files accidentally committed alongside SDK sources - removed. (a032f16)
- **Cloud extras missing from setup verification**: `pyiceberg`, `bcrypt` were not installed during verification, causing cryptic test failures. `make setup` now installs `[dev,integrations,cloud]` extras. (4e86759)
- **Bandit missing from dev verification deps**: `bandit` wasn't in dev extras, breaking security baseline check on clean clones. (cf3a602)
- **Bandit baseline missing from published repo**: `.bandit-baseline.json` was gitignored - required by `test_bandit_diff.py`. Now tracked. (669c9d7)

### Verification

Fresh clone installation flow confirmed:

```bash
git clone https://github.com/brownjuly2003-code/agentflow
cd agentflow
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev,integrations,cloud]'
.venv/Scripts/python -m pytest tests/unit -q  # -> 340 passed
```

---

## [1.0.0] - 2026-04-20

### Added

- Python and TypeScript SDK resilience support: retry policies, circuit breakers, batching helpers, pagination helpers, and contract pinning
- Minimal admin dashboard at `/admin`
- Chaos smoke on pull requests plus scheduled full chaos coverage
- Performance regression gate in CI based on `docs/benchmark-baseline.json`
- Terraform apply workflow with environment approval and OIDC-ready AWS auth
- Fly.io demo deployment config in `deploy/fly/`
- Public-facing docs set: API reference, competitive analysis, security audit, glossary, and publication checklist

### Changed

- Entity lookup latency from the original ~`26,000 ms` baseline to the current `43-55 ms` release range, with entity p99 at `290-320 ms` in the checked-in baseline
- Query safety from regex-style scoping to `sqlglot` AST validation with allowlisted tables
- Hot-path entity reads from string interpolation to parameterized queries
- SDK configuration cleaned up around `configure_resilience()` while preserving backwards compatibility for existing callers

### Fixed

- Windows DuckDB file-lock flake in rotation tests
- Auth auto-revoke regression after the auth module split
- Analytics hot-path regression caused by cache stampede and schema re-bootstrap
- Missing Flink Terraform `application_code_configuration`

### Security

- Parameterized queries throughout the serving hot path
- `sqlglot` AST validator for natural-language-to-SQL translation
- Bandit baseline gate so only new findings fail CI
- API key rotation with grace period and auto-revoke support
