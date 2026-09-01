# Contributing

Complete the [quickstart](quickstart.md) for the first executable local path.
This guide owns change verification, specialist test selection, and local
documentation tooling.

## Recommended Environments

- Local demo: use the [quickstart](quickstart.md) for the fastest DuckDB +
  FastAPI feedback loop.
- Production-shaped local stack: `make stack-prod-shaped-local` when you need Redis, Jaeger, Prometheus, Alertmanager, or Grafana. `make stack-prod-shaped-local-smoke` proves an authenticated request works.
- DevContainer: use `.devcontainer/` when you need one workspace for SDK work, chaos tests, and kind staging.

## Setup

macOS / Linux:

```bash
source ./scripts/setup.sh
```

PowerShell:

```powershell
. .\scripts\setup.ps1
```

After setup, install the TypeScript SDK dependencies if you touch `sdk-ts/`:

```bash
cd sdk-ts && npm install && cd ..
```

## Daily Workflow

1. Run the smallest relevant test slice first.
2. Keep docs in sync with behavior changes, especially `docs/api-reference.md`, `docs/architecture.md`, and `docs/runbook.md`.
3. If you change the HTTP surface, regenerate supporting artifacts with `make tools`.
4. Before opening a change, run at least the checks that cover the files you touched.

## Test Matrix

| Scope | Command | Notes |
|------|---------|-------|
| Lint | `make lint` | Runs Ruff and mypy |
| Unit | `pytest tests/unit/ -v --tb=short` | Fastest signal for Python-only changes |
| CI unit + property coverage | `python -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src/agentflow_runtime --cov=sdk --cov-report=xml:.artifacts/coverage/coverage.xml --cov-report=term-missing --cov-fail-under=60` | Full `src/` + `sdk/` baseline floor in CI; local `diff-cover` enforces 80% on changed lines against ignored `.artifacts/coverage/coverage.xml` |
| Integration | `pytest tests/integration/ -v --tb=short -m integration` | Covers routers, persistence, and service integration without the full prod stack |
| Full Python suite | `make test` | Runs `pytest tests/ -v --tb=short --ignore=tests/load` |
| TypeScript SDK | `cd sdk-ts && npm test` | Runs the Vitest client checks |

CI creates `.artifacts/coverage/` and writes the repository-wide XML to
`.artifacts/coverage/coverage.xml` before `diff-cover` reads that same path.
The file is a replaceable per-run CI working copy, not reviewed evidence or
production acceptance. Reviewed promotion requires a new date-stamped identity
with source SHA, run identity, host/runtime, exact command/configuration/floor,
and artifact hash provenance.

## E2E Tests

Use the E2E suite when a change affects end-to-end agent behavior, auth, pagination, webhooks, or SSE.

```bash
pytest tests/e2e/ -v --tb=short --timeout=60
```

Notes:
- By default the suite starts a temporary local API on a free port.
- To point tests at an already running instance, set `AGENTFLOW_E2E_BASE_URL`.
- If you provide an external instance, also provide matching keys through `AGENTFLOW_E2E_SUPPORT_KEY`, `AGENTFLOW_E2E_OPS_KEY`, and `AGENTFLOW_E2E_RATE_LIMIT_KEY`.

Example against a running prod-like stack:

```bash
export AGENTFLOW_E2E_BASE_URL=http://127.0.0.1:8000
pytest tests/e2e/ -v --tb=short --timeout=60
```

## Chaos Tests

Use the chaos suite when a change touches Redis, Kafka behavior, outbox replay, rate limiting, dead-letter replay, or graceful degradation.

```bash
pytest tests/chaos/ -v --tb=short
```

Notes:
- The suite starts `docker-compose.chaos.yml` automatically.
- Required local ports: `8474`, `19092`, and `16380`.
- Set `SKIP_DOCKER_TESTS=1` only when Docker is intentionally unavailable.

## Staging Rehearsal

For Helm, kind, or deployment changes, use an isolated Docker/kind host and a
promotion packet from one explicit successful `Container Attestation` build.
After validating the run, packet, cosign signature, and GitHub provenance, run:

```bash
PROMOTION_VALUES_FILE=/absolute/path/to/image-values.yaml bash scripts/k8s_staging_up.sh
bash scripts/k8s_staging_down.sh
```

This path exercises registry pull by immutable digest, Helm install, and smoke
validation. It deliberately does not rebuild or `kind load` the API image. The
manual `Staging Deploy` workflow is the complete gate because it performs the
pre-cluster checks and retains the existing E2E suite plus staging evidence.

## Documentation Site

Install the optional site tooling if it is not already available:

```bash
python -m pip install "mkdocs-material>=9.5,<10"
```

Preview the site locally:

```bash
mkdocs serve
```

The API and MkDocs both default to port `8000`. When the API is already using
that port, bind the site to `8010`:

```bash
mkdocs serve -a 127.0.0.1:8010
```

Run the strict static build before submitting documentation changes:

```bash
mkdocs build --strict
```

## Docs and API Changes

If you touch routers, auth, or middleware:
- update `docs/api-reference.md`
- update `docs/runbook.md` if the operational workflow changed
- update `docs/architecture.md` if a component or data flow changed
- run `make tools` if the OpenAPI export should change

If you touch chaos, staging, or observability:
- verify port numbers and commands in `.devcontainer/devcontainer.json`
- verify `docs/runbook.md` still matches the actual recovery flow
- verify `docker-compose.prod.yml` and `docker-compose.chaos.yml` examples still start cleanly
