# Engineering Standards

This page owns the DORA targets, quality gates, CI/CD enforcement, deployment
event shape, and documentation conventions this repository holds itself to.
Read it when changing gates, workflows, or living-page style. It does not
inventory generated quality-gate numbers — that is [quality.md](quality.md) —
and it does not report measured status, which lives in [STATUS.md](STATUS.md).

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
- `python -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src/agentflow_runtime --cov=sdk --cov-report=xml:.artifacts/coverage/coverage.xml --cov-report=term-missing --cov-fail-under=60`
- `pytest tests/integration/ -v --tb=short`
- `python scripts/run_benchmark.py`
- `python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/benchmark/current.json --max-regress 20`
- `terraform fmt -check -recursive infrastructure/terraform/`
- `terraform init -backend=false && terraform validate`

CI creates `.artifacts/coverage/` and writes that ignored XML before local
`diff-cover` enforces 80% on changed lines. The file is a replaceable per-run
CI working copy, not reviewed evidence or production acceptance. Reviewed
promotion requires a new date-stamped identity with source SHA, run identity,
host/runtime, exact command/configuration/floor, and artifact hash provenance.

## CI/CD Enforcement

- Pull requests to `main` must pass lint, mypy, unit + property tests with a full-project coverage floor of `>= 60%`, local `diff-cover` patch coverage at `>= 80%` against `.artifacts/coverage/coverage.xml`, integration tests, schema evolution check, performance regression check, and Terraform validation.
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

## Documentation Conventions

A living page is a tracked `docs/**/*.md` file outside `docs/archive/`, `docs/decisions/`,
`docs/dv2-multi-branch/`, `docs/evidence/`, `docs/migration/` and `docs/perf/`; hubs and indexes
are living pages. Pages under those directories are point-in-time records held to the
[archive contract](archive/README.md), and their historical wording is never modernized.

A page opens with its H1 and one paragraph of purpose. Operator and runbook pages then carry
`**Audience:**` and `**Prerequisites:**` lines; commands appear in fenced blocks and must have
been run as written; every procedure states its failure boundary — what it cannot prove and what
it does not authorize.

A living page carries an `Updated` stamp only when the date is part of the claim the reader must
trust: a status snapshot, an audit result, a rehearsal or resume boundary, a record carrying a
superseded notice. The seven dated pages are [STATUS.md](STATUS.md),
[security-audit.md](security-audit.md),
[api-duckdb-non-target-scratch-rehearsal-runbook.md](operations/api-duckdb-non-target-scratch-rehearsal-runbook.md),
[api-duckdb-persistence-recovery-design.md](operations/api-duckdb-persistence-recovery-design.md),
[ci-soak-next-session-runbook.md](operations/ci-soak-next-session-runbook.md),
[chaos-runbook.md](operations/chaos-runbook.md) and
[ci-soak-compose-foundation.md](operations/ci-soak-compose-foundation.md); each carries exactly
one `**Updated:** YYYY-MM-DD` line (optionally plus a short note) after the H1 and before the
first section heading. Every other living page is undated: its validity comes from verified
commands and links, and Git history is the date. Enforced by:

```powershell
python scripts/check_docs_updated_stamps.py
python scripts/check_docs_anchors.py
python scripts/check_historical_claims.py
```
