# TA04 result

- HEAD audited: `a010a2d`
- Matrix below keeps all 15 workflows and all jobs. For non-test / non-Python jobs the extras audit is marked `N/A` so the deliverable still covers the full workflow surface.
- Consistency with TA01: `ci.yml:test-integration` is already on `.[dev,cloud]` at HEAD, so the old `pyiceberg` regression is now closed and is marked `OK`.

## Extras matrix

| Workflow | Job | pip extras | Test dir | src/ modules transitively | Required extras (from src) | Gap | Action |
|----------|-----|------------|----------|---------------------------|----------------------------|-----|--------|
| Nightly Backup | `backup` | `dev` | `—` | script-only path (`scripts/backup.py`, `verify_backup.py`, `restore.py`) | `—` | `N/A` | `OK (out of test-scope for TA04)` |
| Chaos Engineering | `chaos-smoke` | `dev,cloud` | `tests/chaos/test_chaos_smoke.py` | `tests/chaos/conftest.py` imports `src.serving.api.main`, `src.processing.event_replayer`, `src.serving.cache` | `dev,cloud` | `—` | `OK` |
| Chaos Engineering | `chaos-full` | `dev,cloud` | `tests/chaos/` | `tests/chaos/conftest.py` imports `src.serving.api.main`, `src.processing.event_replayer`, `src.serving.cache` | `dev,cloud` | `—` | `OK` |
| CI | `lint` | `dev` | `—` | lint/type-check only (`ruff`, `mypy`) | `—` | `N/A` | `OK (non-test job)` |
| CI | `schema-check` | `dev` | `—` | script-only path (`scripts/check_schema_evolution.py`) | `—` | `N/A` | `OK (non-test job)` |
| CI | `test-unit` | `root: dev,integrations,cloud`; `subpkg: ./integrations[mcp]` | `tests/unit/`, `tests/property/` | `src.serving.api.main`; `src.quality.monitors.metrics_collector`; `agentflow_integrations.langchain`; `agentflow_integrations.llamaindex`; `agentflow_integrations.mcp.server`; `pyflink` is stubbed in unit tests | `root: dev,cloud`; `subpkg: ./integrations[mcp]` | `overhead: root ,integrations duplicates deps already pulled by ./integrations[mcp]` | `drop ,integrations at ci.yml:61; keep ci.yml:62` |
| CI | `test-integration` | `dev,cloud` | `tests/integration/` | `src.serving.api.main`; `src.processing.local_pipeline`; `src.processing.iceberg_sink`; `src.quality.monitors.metrics_collector`; direct `pyiceberg.exceptions`; `nl_engine` is lazy on `anthropic`; `session_aggregation` is lazy on `pyflink` | `dev,cloud` | `—` | `OK` |
| CI | `perf-check` | `dev,load` | `tests/load/` via `scripts/run_benchmark.py` | `tests/load/locustfile.py`; `scripts/run_benchmark.py` launches `src.processing.local_pipeline` and `uvicorn src.serving.api.main:app` | `load,cloud` | `missing ,cloud` | `add ,cloud at ci.yml:115` |
| CI | `terraform-validate` | `—` | `—` | Terraform-only | `—` | `N/A` | `OK` |
| CI | `record-deployment` | `—` | `—` | git/DORA bookkeeping only | `—` | `N/A` | `OK` |
| Contract Tests | `contract` | `dev,cloud` + `schemathesis` | `tests/contract/` | contract tests import SDK, but `tests.e2e.conftest` defaults to local API startup and runs `uvicorn src.serving.api.main:app` | `dev,cloud` | `—` | `OK` |
| DORA Metrics | `dora-report` | `—` | `—` | script-only path (`scripts/dora_metrics.py`) | `—` | `N/A` | `OK` |
| E2E Tests | `e2e` | `dev` + `requirements.txt` + `click rich pyyaml pytest-timeout` | `tests/e2e/` | host-side tests import `agentflow`, `httpx`, `yaml`; workflow points tests to external compose stack via `AGENTFLOW_E2E_BASE_URL` | `dev` | `—` | `OK` |
| Load Test | `load-test` | `load,cloud` | `tests/load/` | `tests/load/locustfile.py`; workflow starts `uvicorn src.serving.api.main:app`; `scripts/check_performance.py` is base-only | `load,cloud` | `—` | `OK` |
| Mutation Testing | `mutation` | `requirements.txt` + `dev,integrations` | `scripts/mutation_report.py` targets `tests/unit/test_auth.py`, `tests/property/test_auth_properties.py`, `tests/unit/test_masking.py`, `tests/property/test_masking_properties.py`, `tests/unit/test_db_pool.py`, `tests/integration/test_outbox.py`, `tests/unit/test_rate_limiter.py` | targeted tests pull `src.quality.monitors.metrics_collector` and `src.serving.api.main`; no targeted test imports `agentflow_integrations.*` | `dev,cloud` | `missing ,cloud; overhead ,integrations` | `replace .[dev,integrations] with .[dev,cloud] at mutation.yml:23` |
| Performance Regression | `perf-regression` | `dev,load,cloud` | `tests/load/` via `scripts/run_benchmark.py` | `tests/load/locustfile.py`; `src.processing.local_pipeline`; `src.serving.api.main` | `dev,load,cloud` | `—` | `OK` |
| Nightly Performance | `performance-regression` | `dev,load,cloud` | `tests/load/` via `scripts/run_benchmark.py` | `tests/load/locustfile.py`; `src.processing.local_pipeline`; `src.serving.api.main` | `dev,load,cloud` | `—` | `OK` |
| Publish TypeScript SDK | `publish` | `—` | `—` | npm-only job | `—` | `N/A` | `OK` |
| Publish Python SDK | `publish` | `—` (`build`, `twine` only) | `—` | build/publish only | `—` | `N/A` | `OK` |
| Security Scan | `bandit` | `—` (`bandit` only) | `—` | security script path (`scripts/bandit_diff.py`) | `—` | `N/A` | `OK` |
| Security Scan | `safety` | `—` (`safety` only) | `—` | dependency audit only | `—` | `N/A` | `OK` |
| Security Scan | `trivy` | `—` | `—` | container scan only | `—` | `N/A` | `OK` |
| Staging Deploy | `staging` | `dev` + `requirements.txt` + `click rich pyyaml pytest-timeout` | `tests/e2e/test_smoke.py::test_rate_limit_returns_429_after_threshold`, `tests/e2e/` | host-side tests import `agentflow`, `httpx`, `yaml`; workflow points tests to external staging URL via `AGENTFLOW_E2E_BASE_URL` | `dev` | `—` | `OK` |
| Terraform Apply | `plan` | `—` | `—` | Terraform-only | `—` | `N/A` | `OK` |
| Terraform Apply | `apply` | `—` | `—` | Terraform-only | `—` | `N/A` | `OK` |

## Findings

1. `ci.yml:115` is the only active Python test/perf gap left inside `CI`: `perf-check` installs `.[dev,load]`, but `scripts/run_benchmark.py` starts both `src.processing.local_pipeline` and `src.serving.api.main:app`, and those paths transitively require `pyiceberg` via `src/processing/local_pipeline.py:22` and `src/quality/monitors/metrics_collector.py:19`. Recommended PR: `add ,cloud`.
2. `mutation.yml:23` is a latent mis-match: `scripts/mutation_report.py:45` and `:54` target `tests/unit/test_db_pool.py` and `tests/integration/test_outbox.py`, which transitively import `metrics_collector` / `main` and therefore require `cloud`, while the current install line carries unused `integrations`. Recommended PR: `swap ,integrations -> ,cloud`.
3. `ci.yml:test-unit` has one confident overhead: `ci.yml:61` installs root `,integrations`, but `ci.yml:62` already installs `./integrations[mcp]`, and that subpackage pulls `langchain`, `llama-index-core`, and `mcp`. The tests that need those deps are `tests/unit/test_langchain_tool.py:10`, `tests/unit/test_llamaindex_reader.py:9`, and `tests/unit/test_mcp_server.py:20`. Recommended PR: `drop root ,integrations`, keep `./integrations[mcp]`.

## Notes

- `llm` is not required by any current CI job. `src/serving/semantic_layer/nl_engine.py` imports `anthropic` only inside `_llm_translate()`, and `tests/integration/test_query_explain.py:107` injects a fake `anthropic` module instead of requiring the real extra.
- `flink` is not required by any current CI job. `tests/unit/test_stream_processor.py:226-421` and `tests/unit/test_session_aggregator.py:114-274` seed fake `pyflink` modules in `sys.modules`, while `src/processing/flink_jobs/checkpointing.py` and `src/processing/flink_jobs/session_aggregation.py` gate real `pyflink` behind runtime imports/fallbacks.
- Search in `requirements.txt` found no optional-dependency packages such as `pyiceberg`, `locust`, `langchain`, `llama_index`, `mcp`, or `pyflink`, so host jobs cannot rely on `requirements.txt` to mask an extras gap.
