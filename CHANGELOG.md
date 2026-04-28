# Changelog

All notable changes to AgentFlow are documented in this file.

## [Unreleased]

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
`integrations/pyproject.toml` resolved requirements.

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
of this set but its bot push couldn't pre-satisfy the gate
(chicken-and-egg: a self-push to a branch with 13 required
checks can't satisfy them at push time); the job was removed
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
import from `"@agentflow/client"` (was `"agentflow"`); placeholder
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
