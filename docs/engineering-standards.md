# Engineering Standards

## DORA Targets

| Metric | Elite benchmark | Our target |
|--------|-----------------|------------|
| Deployment frequency | Multiple/day | Daily |
| Lead time | < 1 hour | < 1 day |
| Change failure rate | < 5% | < 15% |
| MTTR | < 1 hour | < 4 hours |

`python scripts/dora_metrics.py --days 30 --output .artifacts/dora/dora-report.json` is the canonical local report for the last 30 days. The default destination is that ignored runtime file; relative `--output` paths resolve from the project root. The result is host-, time-, and GitHub-history-dependent evidence, not production acceptance and not a byte-regenerated reference. `.github/workflows/dora.yml` writes the same JSON plus `dora-summary.md` and `dora-comment.md` under `.artifacts/dora/`, uploads the report/summary as the `dora-report` artifact, and updates the pinned PR comment. Promote a reviewed snapshot only under a new date-stamped identity with source SHA, window/branch, data sources, exact command/configuration, host/runtime, and artifact hash provenance. In this repo, a successful push to `main` is treated as a deployment because CI is the last gate before release packaging.

## Quality Gates

- `ruff check src/ tests/`
- `ruff format --check src/ tests/`
- `mypy src/ --ignore-missing-imports`
- `python scripts/check_schema_evolution.py`
- `python -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src/agentflow_runtime --cov=sdk --cov-report=xml --cov-report=term-missing --cov-fail-under=60`
- `pytest tests/integration/ -v --tb=short`
- `python scripts/run_benchmark.py`
- `python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/benchmark/current.json --max-regress 20`
- `terraform fmt -check -recursive infrastructure/terraform/`
- `terraform init -backend=false && terraform validate`

## CI/CD Enforcement

- Pull requests to `main` must pass lint, mypy, unit + property tests with a full-project coverage floor of `>= 60%`, Codecov patch coverage at `>= 80%`, integration tests, schema evolution check, performance regression check, and Terraform validation.
- Pushes to `main` append a JSONL deployment event to `.dora/deployments.jsonl` inside the workflow workspace and upload it as an artifact for auditability.
- `scripts/dora_metrics.py` prefers GitHub Actions history when `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are available; otherwise it falls back to local git history and `.dora/deployments.jsonl`.
- Weekly DORA reporting lives in `.github/workflows/dora.yml` and publishes a markdown summary. On pull requests, the workflow also updates a pinned DORA comment.

## Deployment Event Shape

Each line in `.dora/deployments.jsonl` contains:

- `recorded_at`
- `sha`
- `ref`
- `workflow`
- `run_id`
- `status`
- `html_url`
- `jobs`
