# AgentFlow quality gates

Generated from [`config/project_claims.toml`](../config/project_claims.toml) by `python scripts/export_quality_reference.py`. Edit the manifest, not this list.

## Enforced gates
- Project coverage floor: 60%
- Patch coverage floor: 80%
- Critical-module coverage floor: 90%
- MkDocs strict build: required

## Verification

- Regenerate this reference with `python scripts/export_quality_reference.py`.
- Check tracked drift with `python scripts/export_quality_reference.py --check`.
- Validate the claims against CI and Codecov configuration with `python scripts/validate_project_claims.py`.

## Local quality snapshots

- Coverage: published from source `coverage.xml` only by a host-specific snapshot when that artifact is fresh; this deterministic reference owns the configured floors above.

Run `python scripts/quality_report.py --skip-docker --skip-dependency-scans` for a host- and time-specific report. Its default output is `.artifacts/quality/quality-report.md`, which is intentionally ignored.

A local snapshot can depend on test collection, coverage age, security tools, and mutation, chaos, and load artifacts. It is not a cross-host current reference. The last tracked dynamic snapshot is preserved as [historical generated output](archive/quality-report-2026-07-23.md).
