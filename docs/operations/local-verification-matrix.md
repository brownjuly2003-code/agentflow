# Local Verification Matrix

This guide defines which verification commands are safe for the guarded local
autopilot path and which commands require Docker, cloud credentials, external
services, or manual operator intent.

## Windows Workstation No-Docker Policy

Treat this Windows workstation as a no-Docker host. Do not start Docker Desktop,
`docker compose`, `docker build`, kind, Helm live validation, chaos tests, or a
Docker-dependent full pytest run here; Docker has been observed to hang local
processes on this machine.

Run Docker-heavy validation on the Mac runner or in CI. When reporting local
evidence from this machine, use wording like `local no-Docker green; Docker-heavy
verification pending on Mac/CI` unless the Mac or CI evidence is already attached
with command, commit SHA, and result.

Current Mac host note: iMac `julia@192.168.1.133` is reachable by SSH and can
run Docker through Lima. On 2026-05-30 it had Docker Engine `29.5.2` and the
user-local Docker Compose CLI plugin `v5.1.4`; the repo checkout lives at
`/Users/julia/agentflow-docker-check`. This is not a GitHub Actions
self-hosted runner (`gh api .../actions/runners` reported `total=0`). It can
provide manual Docker build/compose evidence, and pytest-based Docker suites can
use `/Users/julia/agentflow-docker-check/.venv-mac-docker`.

## Default Safe Gates

Run these commands by default when the touched files make them relevant. They
do not deploy, publish packages, read secrets, or require live external
accounts.

| Scope | Command | Use when |
| --- | --- | --- |
| Whitespace | `git diff --check` | Always before handoff, commit, or autopilot retry. |
| Python unit tests | `python -m pytest tests/unit -p no:schemathesis` | Python source, SDK, or unit-test changes. |
| Targeted Python test | `python -m pytest <test-path> -p no:schemathesis` | TDD loop for one file or one test node. |
| No-Docker broad pytest | `$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis` | Broad local regression on this Windows workstation. |
| Ruff lint | `python -m ruff check src/ tests/` | Any Python source or test change. |
| Ruff format check | `python -m ruff format --check src/ tests/` | Any Python source or test change. |
| mypy | `python -m mypy src/` | Typed serving, processing, or SDK-adjacent Python changes. |
| TypeScript SDK typecheck | `cd sdk-ts; npm run typecheck` | TypeScript SDK source or type changes. |
| TypeScript SDK unit tests | `cd sdk-ts; npm run test:unit` | TypeScript SDK behavior or client contract changes. |
| TypeScript SDK build | `cd sdk-ts; npm run build` | TypeScript SDK source, package, or export changes. |
| Contract generation check | `python scripts/generate_contracts.py --check` | API contract or generated-schema changes. |
| Bandit diff | `bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp/bandit-current.json; python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json` | Security-sensitive Python changes. |

Install local dependencies before a fresh verification environment:

```powershell
python -m pip install -e ".[dev,cloud]"
python -m pip install -e "./sdk"
python -m pip install -e "./integrations[mcp]"
cd sdk-ts
npm install
cd ..
```

## Docker-Dependent Gates

These commands are not safe on this Windows workstation. They start containers,
require Docker health, or depend on reserved local ports. Use the Mac runner or
CI for them.

| Scope | Command | Requirements |
| --- | --- | --- |
| Full Docker-capable pytest | `python -m pytest -p no:schemathesis` | Run on Mac/CI when Docker-dependent tests must be included. On this Windows host use the `SKIP_DOCKER_TESTS=1` gate above. |
| Integration tests | `python -m pytest tests/integration -v --tb=short` | Kafka and service dependencies; CI starts Kafka for the main integration job. |
| Helm live validation | `python -m pytest tests/integration/test_helm_values_live_validation.py -v -m integration --tb=short` | Helm/kind tooling. |
| E2E tests | `python -m pytest tests/e2e -v --tb=short --timeout=60` | Temporary local API, or an explicit `AGENTFLOW_E2E_BASE_URL` and matching test keys. |
| Chaos smoke | `python -m pytest tests/chaos/test_chaos_smoke.py -v --tb=short` | Docker compose chaos services and ports `8474`, `19092`, and `16380`. |
| Full chaos | `python -m pytest tests/chaos/ --ignore=tests/chaos/test_chaos_smoke.py -v --tb=short` | Docker compose chaos services; prefer the dedicated chaos runbook. |
| Demo stack | `make demo` | Redis via Docker and a foreground API server. |
| Prod-like stack | `docker compose -f docker-compose.prod.yml up -d` | Local Docker resources and operator intent. |

Latest Mac Docker build/compose health smoke evidence (historical evidence; not
current HEAD evidence) at checkout HEAD `ffeb423`:

```bash
docker build -f Dockerfile.api -t agentflow-api:mac-docker-smoke-ffeb423 .
docker compose -p agentflow-e2e-mac -f docker-compose.e2e.yml up -d --build --wait agentflow-api
curl -fsS http://127.0.0.1:8000/v1/health
docker compose -p agentflow-e2e-mac -f docker-compose.e2e.yml down -v
```

The build passed. The e2e compose stack brought Redis, Postgres, Kafka, and the
API to Docker `Healthy`; `/v1/health` reported `kafka:healthy` and
`duckdb_pool:healthy`. The aggregate health JSON stayed `unhealthy` because
Flink, Iceberg, freshness, and quality signals are outside the e2e compose
stack. Cleanup removed the `agentflow-e2e-mac` containers, network, and volume.

Latest Mac pytest compose smoke evidence after commit `677de80`:

```bash
AGENTFLOW_E2E_MODE=compose AGENTFLOW_E2E_TIMEOUT=180 .venv-mac-docker/bin/python -m pytest tests/e2e/test_smoke.py -v --tb=short -p no:schemathesis --basetemp .tmp/mac-e2e-smoke-basetemp -o cache_dir=.tmp/mac-e2e-smoke-cache
```

That run passed with `10 passed in 121.10s`, including the webhook callback
test. The Mac/Lima callback host is `host.lima.internal`; Linux/CI remains on
`host.docker.internal`, and `AGENTFLOW_E2E_CALLBACK_HOST` can still override the
callback host explicitly. Cleanup left only the pre-existing `hq-demo` kind
containers.

Latest Windows no-Docker audit-remediation evidence at HEAD `65863f8`:

```powershell
python scripts\export_openapi.py --check
python -m pytest tests\unit\test_export_openapi.py tests\contract -p no:schemathesis
$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis --basetemp .tmp\codex-query-engine-full-basetemp -o cache_dir=.tmp\codex-query-engine-full-cache
python -m pytest tests\unit\test_quality_report.py -q -p no:schemathesis
python scripts\quality_report.py --skip-docker --skip-dependency-scans
python -m pytest tests\unit\test_contract_dependencies.py tests\unit\test_security_workflow.py tests\unit\test_container_attestation_workflow.py -q -p no:schemathesis
python -m ruff check src/ tests/ scripts\export_openapi.py
python -m ruff format --check src/ tests/ scripts\export_openapi.py
python -m mypy scripts\quality_report.py
git diff --check
```

The export check passed; targeted contract/unit tests passed with 18 tests and
104 warnings; broad no-Docker pytest passed with 846 passed, 32 skipped, and
104 warnings; quality-report tests passed with 8 tests; prod-compose/security
workflow policy tests passed with 22 tests; targeted ruff, format, mypy, and
whitespace checks passed. GitHub evidence on current HEAD `65863f8`: push CI,
Contract Tests, Security Scan, E2E Tests, and Staging Deploy completed
successfully. Push Load Test run `26677145590` failed from broad p99 runner
slowdown with no functional request failures; manual Load Test reruns
`26677294150` and `26677355752` on the same SHA both completed successfully per
the load-regression runbook's runner-variance check.

## Benchmark And Load Gates

Benchmarks are safe only when the caller explicitly wants performance evidence.
They are not default autopilot gates because they can start services, generate
runtime databases, and consume substantial time.

| Scope | Command | Notes |
| --- | --- | --- |
| Canonical benchmark | `python scripts/run_benchmark.py` | Writes benchmark artifacts and may overwrite `docs/benchmark.md`. |
| Nightly-style benchmark | `python scripts/run_benchmark.py --results-json .artifacts/benchmark/current.json --report-path .artifacts/benchmark/benchmark.md` | Mirrors `.github/workflows/performance.yml`. |
| Benchmark comparison | `python scripts/check_performance.py docs/benchmark-baseline.json .artifacts/benchmark/current.json` | Requires a current benchmark JSON. |
| CI smoke load gate | `python tests/load/run_load_test.py --host http://127.0.0.1:8011 --stats-prefix .artifacts/load/results --results-json .artifacts/load/results.json` | Requires seeded data and a running local API. |
| Load regression comparison | `python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/load/results.json --max-regress 50` | Requires load-test output. |

## Security Gates

The Bandit diff gate is safe by default when security-sensitive Python changes
are in scope. The remaining security workflows need extra operator intent.

| Scope | Command | Default status |
| --- | --- | --- |
| Bandit baseline diff | `bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp/bandit-current.json; python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json` | Safe local gate. |
| Safety dependency scan | `safety check -r .tmp-security/requirements-main.txt -r .tmp-security/requirements-sdk.txt -r .tmp-security/requirements-integrations.txt` | Requires resolved `.tmp-security` requirements first. |
| npm audit | `cd sdk-ts; npm audit --audit-level=moderate` | Safe after dependencies are installed; may use the npm registry. |
| Trivy image scan | `docker compose -f docker-compose.prod.yml build agentflow-api` then Trivy scan | Docker/image build required; not a default autopilot gate. |
| Release artifact secret check | `python scripts/check_release_artifacts.py <artifact-path>` | Safe only against explicit build artifacts. |

## Forbidden Default Paths

Do not run these from autopilot or routine local verification unless the user
explicitly assigns a bounded operator task:

- `terraform apply`, production Terraform plans that use live credentials, or
  cloud account mutations.
- `npm publish`, `npm login`, `npm token`, `twine upload`, PyPI publishing, or
  package ownership changes.
- GitHub release publishing, deployment workflows, staging deploys, production
  Docker rollouts, or Kubernetes/Helm changes against live clusters.
- Commands that print or rotate secrets, modify cloud IAM, or call paid external
  APIs.

## Autopilot Gate Policy

The guarded autopilot runner should always run `git diff --check`. It may run
Python, Ruff, mypy, and TypeScript SDK gates when changed paths require them and
the commands are available locally. On this Windows workstation, broad pytest
must set `SKIP_DOCKER_TESTS=1`; Docker-required gates must be recorded as
Mac/CI-pending evidence instead of attempted locally. It should record missing
tooling as a runtime gap in `AGENT_STATE.md` instead of silently trusting an
unverified area.
