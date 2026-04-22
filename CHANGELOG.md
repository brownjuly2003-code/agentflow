# Changelog

All notable changes to AgentFlow are documented in this file.

## [Unreleased]

v1.1 sprint work. Commits staged on `main` but not yet pushed; this
section will be renamed on release tag.

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
- **`integrations/` package bumped to 1.0.1** with the `mcp`
  optional extra and an `agentflow-mcp` console script; the stale
  `agentflow-client>=0.1.0` dependency now points at the public
  `agentflow>=1.0.1`. (07cb253)
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

Test suite status at sprint close: **411 tests passing**, 1 skipped,
0 regressions.

| Suite | Count | Duration |
|-------|-------|----------|
| unit | 360 | ~60 s |
| property + contract + sdk | 38 | ~31 s |
| e2e (non-dagster) | 13 | ~63 s |

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
