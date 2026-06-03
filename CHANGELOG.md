# Changelog

All notable changes to AgentFlow are documented in this file.

## [Unreleased]

### Fixed

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
  `src/serving/api/auth/middleware.py`. Closes Kimi audit L-C4
  ("DB utilities don't belong in a middleware file"). Public callers
  go through `AuthManager.*` shim methods unchanged; the only direct
  importer was `tests/unit/test_audit_publisher.py`, repointed to the
  new module. Middleware drops four dead imports (`duckdb`, `time`,
  `pathlib.Path`, `AuthManager`).

### Performance

- `scripts/perf/auth_bench.py` + `docs/perf/auth-bench-2026-05-26.md`
  — perf-baseline microbench closing two deferred Kimi audit findings.
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
  pure-Python config builders. Closes Kimi audit R4: both files
  went from 0% to 100% combined (line+branch) unit coverage; total
  `src.ingestion` rose 82% → ~85%. Tests pin the operational knobs
  the `cdc-lag` runbook depends on (snapshot mode, heartbeat
  interval, custom metric tags) so accidental drift fails the unit
  step instead of surfacing as silent capture gap.

### Changed

- `.github/workflows/contract.yml` now triggers on
  `infrastructure/terraform/**`, `sdk-ts/**`, and `Dockerfile*`
  paths in addition to the existing src/sdk/pyproject/workflows
  set. Closes Kimi audit R2 and removes the last remaining
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
  Closes Kimi audit R6. A new
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
  `stream_processor`. Closes Kimi audit R7.

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
  the retry loop. Closes Kimi audit H-C3. Two regression tests in
  `tests/unit/test_audit_publisher.py` pin the contract:
  `test_record_usage_no_duplicate_insert_when_publish_raises` and
  `test_record_usage_skips_publish_when_all_inserts_fail`.
- The lifespan-time `SearchIndex.rebuild()` call in
  `src/serving/api/main.py` is now wrapped so a catalog/query-engine
  failure during initial index build leaves the API up with a
  warning (`search_index_initial_rebuild_failed`) instead of
  aborting startup. The 60-second periodic rebuilder (which already
  catches its own exceptions) is still scheduled, so the search
  surface can recover without a process restart. Closes Kimi audit
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
  continue to collapse. Closes part of Kimi audit H-C2 (literal
  corruption vector). Seven regression tests in
  `tests/unit/test_clickhouse_backend.py::TestTranslateSqlLiteralProtection`
  pin the contract against `::FLOAT`, `NOW()`, `COUNT(*)`, `TRUE`,
  `CAST(... AS FLOAT)`, and `''`-escape forms inside literals.
- `ClickHouseBackend` HTTPS targets now validate the server cert
  against the system trust store explicitly via
  `ssl.create_default_context()` plumbed through to `urlopen`. Insecure
  HTTP backends (default for local-compose) omit the context kwarg so
  Python's `http.client` path is unchanged. Closes part of Kimi audit
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
  runs. Closes Kimi audit H-C1. 13 new regression tests in
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
  deployments are unchanged. Closes Kimi audit L-C2. Regression test
  `test_mysql_server_id_overridable_via_env` covers env override,
  invalid-int fallback, and unset-env fallback.
- `_CONNECT_SECRET_KEY` in `src/ingestion/connectors/{mysql,postgres}_cdc.py`
  is now the literal `"password"` (with `# noqa: S105` documenting that
  it is a property *key name* inside the Kafka Connect
  `FileConfigProvider` `${file:/path:<key>}` syntax, not a credential).
  The previous `"pass" + "word"` concatenation was security through
  obscurity — bytecode collapses the expression and string scanners
  still see the result. Closes Kimi audit L-C1.
- Redundant `event_type == prefix` clauses dropped from
  `src/quality/validators/{schema,semantic}_validator.py`. Python's
  `str.startswith(prefix)` already returns True for the exact-equality
  case (`"order.".startswith("order.")`), so the `or event_type == prefix`
  branch could never fire when the prefix was a non-empty string.
  Closes Kimi audit L-C3.
- `AuthManager` no longer grows its `_rate_windows`,
  `_failed_auth_windows`, and `_runtime_plaintext_by_hash` dictionaries
  unbounded. A new `_sweep_expired_windows()` helper drops entries
  whose entire window has aged past the configured cutoff and runs (a)
  on every config reload under `_config_lock`, and (b) opportunistically
  on every successful `clear_failed_auth` call (the post-auth hot path
  is cheap and bounds growth between reloads). `load()` also purges
  cached plaintext-by-hash entries for hashes that no longer appear in
  the live `_hashed_keys` list, so a revoked/rotated key's plaintext
  cannot remain pinned in memory across reloads. Closes Kimi audit
  H-C4. Regression tests in
  `tests/unit/test_auth_manager_memory_bounds.py` cover the sweep on
  load, the sweep on clear, the plaintext cache purge, and idempotency
  on empty state.

## [1.4.0] - 2026-05-25

Maintenance release. No runtime API changes; bundles documentation,
CI hardening, repo hygiene, type-stub adoption, and Dependabot Tier A
wave 2 dependency bumps that landed in sessions 11–19.

### Documentation

- Top-level [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) — the
  entry point for picking up the project cold. Includes the four
  orientation commands to run first, the priority-tiered open work
  (Tier A actionable Dependabot PRs, Tier B externally user-gated
  A04/A05/A03, Tier C forward backlog), a compressed view of sessions
  11 → 17, and the load-bearing lessons from session 17's regression
  (Contract Tests path filter, Dependabot cascade transitive
  conflicts, memory-staleness check before recommending). README
  surfaces it at the top of the Documentation index.

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
  intentionally kept available — see SESSION_HANDOFF.md anti-tasks).
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
- Recorded the npm Trusted Publishing handoff: the new package was first
  published as `@yuliaedomskikh/agentflow-client@1.1.0`, Trusted Publisher
  setup succeeded for `brownjuly2003-code/agentflow` with workflow
  `publish-npm.yml`, CLI `npm trust list` readback is complete, and future
  recovery-code use must keep a two-code reserve through the
  `npm-recovery-codes` skill.
- Documented the completed replacement npm account bootstrap for
  `yulia.edomskikh@gmail.com`, the saved 2FA recovery-code reserve, and the
  switch of future TypeScript SDK publishing to
  `@yuliaedomskikh/agentflow-client`.
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

Two external audits delivered against `4a13d36` (Claude Opus + Codex p1–p9,
archived under `docs/audits/2026-04-27/`). Six commits closed all
P0/P1/P2 findings.

**Tenant isolation across the control plane (Codex p1 R3/R5, p2_1 #1-3,
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

**SQL guard centralization (Codex p2_1 #4, p2_2 #4, p3 #1):** new
`_prepare_nl_sql()` helper in `nl_queries.py` is the only path that
validates translated SQL via `validate_nl_sql()`; called from
`execute_nl_query`, `paginated_query`, and `explain` before tenant
scoping and pagination wrapping. Closes the bypass on `/v1/query`
(paginated) and `/v1/query/explain`. PII masking and explain
`tables_accessed` rewritten on `sqlglot` AST so tenant-quoted SQL like
`"acme"."users_enriched"` is correctly extracted (Codex p3 #3).

**Entity allowlist enforcement (Codex p2_1 #4, p3 #2):** new
`tenant_key_allowed_tables()` helper in `auth/manager.py`. Applied to
NL query / explain / paginated query, batch query/metric items,
`/v1/search` (intersection with tenant key allowlist + post-filter so
metric documents are not silently dropped for scoped keys), and
`/v1/metrics/{metric}`.

**Auth fail-closed + entropy + scopes (Codex p2_1 #5, p2_2 #1-3):**
auth middleware now fails closed with `503` when no API keys are
configured; opt out with `AGENTFLOW_AUTH_DISABLED=true` for local dev
or `app.state.auth_disabled = True` for tests. Failed-auth throttling
extended to `/v1/admin/*`. `X-Forwarded-For` honoured only when the
immediate peer is in `AGENTFLOW_TRUSTED_PROXIES`. Generated API keys
now use `secrets.token_urlsafe(32)` (256-bit) instead of
`secrets.token_hex(4)` (32-bit).

**Secret hygiene (Codex p2_2 #5/8, p9 #4-5):** rotated active webhook
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

**Supply chain (Codex p9):** committed `sdk-ts/package-lock.json`
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

**OpenAPI drift gate (Codex p4 #5):** `scripts/export_openapi.py`
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

**Python SDK alignment with server v1 contract (Codex p8 F1–F10):**
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

**Test coverage gaps (Codex p5):** new unit suites covering
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
(closes Codex review P2 on auth/middleware persistence).

**Documentation hygiene (Codex p6):** TypeScript SDK examples now
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

**Audits archived:** the two source audits and the two CX task specs
that drove the impl are kept under `docs/audits/2026-04-27/` with a
README that maps findings to the six closing commits.

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

- v1.1 sprint task briefs under `docs/codex-tasks/2026-04-22/`
  (T01-T10, self-contained one-PR ТЗ). (f448626)
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
