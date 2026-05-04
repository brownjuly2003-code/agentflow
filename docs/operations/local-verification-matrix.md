# Local Verification Matrix

This guide defines which verification commands are safe for the guarded local
autopilot path and which commands require Docker, cloud credentials, external
services, or manual operator intent.

## Default Safe Gates

Run these commands by default when the touched files make them relevant. They
do not deploy, publish packages, read secrets, or require live external
accounts.

| Scope | Command | Use when |
| --- | --- | --- |
| Whitespace | `git diff --check` | Always before handoff, commit, or autopilot retry. |
| Python unit tests | `python -m pytest tests/unit -p no:schemathesis` | Python source, SDK, or unit-test changes. |
| Targeted Python test | `python -m pytest <test-path> -p no:schemathesis` | TDD loop for one file or one test node. |
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

## Docker-Dependent Local Gates

These commands are local, but not safe as autopilot defaults because they start
containers, require Docker health, or depend on reserved local ports.

| Scope | Command | Requirements |
| --- | --- | --- |
| Integration tests | `python -m pytest tests/integration -v --tb=short` | Kafka and service dependencies; CI starts Kafka for the main integration job. |
| Helm live validation | `python -m pytest tests/integration/test_helm_values_live_validation.py -v -m integration --tb=short` | Helm/kind tooling. |
| E2E tests | `python -m pytest tests/e2e -v --tb=short --timeout=60` | Temporary local API, or an explicit `AGENTFLOW_E2E_BASE_URL` and matching test keys. |
| Chaos smoke | `python -m pytest tests/chaos/test_chaos_smoke.py -v --tb=short` | Docker compose chaos services and ports `8474`, `19092`, and `16380`. |
| Full chaos | `python -m pytest tests/chaos/ --ignore=tests/chaos/test_chaos_smoke.py -v --tb=short` | Docker compose chaos services; prefer the dedicated chaos runbook. |
| Demo stack | `make demo` | Redis via Docker and a foreground API server. |
| Prod-like stack | `docker compose -f docker-compose.prod.yml up -d` | Local Docker resources and operator intent. |

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
the commands are available locally. It should record missing tooling as a
runtime gap in `AGENT_STATE.md` instead of silently trusting an unverified area.
