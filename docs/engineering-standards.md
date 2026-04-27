# Engineering Standards

## DORA Targets

| Metric | Elite benchmark | Our target |
|--------|-----------------|------------|
| Deployment frequency | Multiple/day | Daily |
| Lead time | < 1 hour | < 1 day |
| Change failure rate | < 5% | < 15% |
| MTTR | < 1 hour | < 4 hours |

`python scripts/dora_metrics.py --days 30 --output dora-report.json` is the canonical report for the last 30 days. In this repo, a successful push to `main` is treated as a deployment because CI is the last gate before release packaging.

## Quality Gates

- `ruff check src/ tests/`
- `ruff format --check src/ tests/`
- `mypy src/ --ignore-missing-imports`
- `python scripts/check_schema_evolution.py`
- `python -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src --cov=sdk --cov-report=xml --cov-report=term-missing --cov-fail-under=60`
- `pytest tests/integration/ -v --tb=short`
- `python scripts/run_benchmark.py`
- `python scripts/check_performance.py docs/benchmark-baseline.json /tmp/current.json`
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
