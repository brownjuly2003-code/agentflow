# Changelog

All notable changes to AgentFlow are documented in this file.

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
