# TA07 result

- Snapshot: local `HEAD a010a2d95001ad7105454eb60fd252bd296a3c7d` on `main`.
- Scan date: `2026-04-23`.
- Raw artifacts: `audit-trivy-all.txt`, `audit-trivy-actionable.txt`, `audit-bandit-diff.txt`, `audit-safety.txt`.

## Security posture (HEAD a010a2d95001ad7105454eb60fd252bd296a3c7d, scan date 2026-04-23)

### Trivy

- Scan target: `agentflow-security-agentflow-api:latest`, built via `docker compose -f docker-compose.prod.yml build agentflow-api`, then tagged as `agentflow-api:security-scan`.
- Total HIGH/CRITICAL: `6` (`HIGH 6`, `CRITICAL 0`).
- Actionable (with fix): `0`.
- Unfixed (ignored by `ignore-unfixed`): `6`.
- CI/root cause: local scan matches the green `security.yml` behavior. Every HIGH finding is unfixed in the current Debian 13.4 base image, so `ignore-unfixed: true` legitimately suppresses them and there is no CI/local mismatch to investigate.
- T04 pin adequacy: confirmed for the prod scan path. `docker-compose.prod.yml` still upgrades `setuptools==82.0.1` and `wheel==0.47.0`, and the current Trivy scan reports no HIGH/CRITICAL findings on either package. `Dockerfile.api` is out of sync with that inline prod build, but it is not the image path scanned by `security.yml`.

| Severity | CVE | Package | Version | Fix-version | Status (action) |
|----------|-----|---------|---------|-------------|-----------------|
| HIGH | `CVE-2025-69720` | `libncursesw6` | `6.5+20250216-2` | `-` | Accept for now; no upstream fix is published in current Trivy DB. Re-review after the next `python:3.11-slim` / Debian base refresh. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2025-69720`. |
| HIGH | `CVE-2025-69720` | `libtinfo6` | `6.5+20250216-2` | `-` | Accept for now; same re-review window as the other `ncurses` packages. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2025-69720`. |
| HIGH | `CVE-2025-69720` | `ncurses-base` | `6.5+20250216-2` | `-` | Accept for now; same re-review window as the other `ncurses` packages. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2025-69720`. |
| HIGH | `CVE-2025-69720` | `ncurses-bin` | `6.5+20250216-2` | `-` | Accept for now; same re-review window as the other `ncurses` packages. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2025-69720`. |
| HIGH | `CVE-2026-29111` | `libsystemd0` | `257.9-1~deb13u1` | `-` | Accept for now; no fixed package version is published in current Trivy DB. Re-review after the next Debian security rollup in the base image. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2026-29111`. |
| HIGH | `CVE-2026-29111` | `libudev1` | `257.9-1~deb13u1` | `-` | Accept for now; same re-review window as `libsystemd0`. Draft: `chore(security): refresh prod base image once Debian ships a fix for CVE-2026-29111`. |

### Bandit diff vs baseline

- `audit-bandit-diff.txt` reports `No new findings (baseline: 1 issues)`.
- Current medium+ scan still contains one existing baseline issue: `B310` at `src/serving/backends/clickhouse_backend.py:49` (`urlopen(request, timeout=...)`).
- No regression was introduced on HEAD, so no new Bandit ticket is required from TA07.

| File:Line | Severity | Issue | Recommendation |
|-----------|----------|-------|----------------|
| `-` | `-` | No new findings versus `.bandit-baseline.json`. Existing baseline entry remains `B310` in `src/serving/backends/clickhouse_backend.py:49`. | Keep the baseline entry as-is; re-review only if the ClickHouse URL stops being config-controlled and becomes user-controlled. |

### Safety

- `audit-safety.txt` is green, but the output says `No packages found`.
- The reproduced workflow input files `.tmp-security/requirements-main.txt` and `.tmp-security/requirements-sdk.txt` contain version ranges from `pyproject.toml` and `requirements.txt` such as `fastapi>=0.111,<1`, not resolved installed versions.
- This means the current Safety job is a false-green signal on HEAD: it is not proving that the dependency set is vulnerability-free, only that Safety could not map the manifest entries to concrete packages.
- Follow-up ticket created: `docs/codex-tasks/2026-04-24/T14-security-safety-resolved-dependency-scan.md`.

| Package | Vulnerability | Affected | Fixed-in | Action |
|---------|---------------|----------|----------|--------|
| `-` | Safety scanned `0` packages and reported `No packages found` | `.tmp-security/requirements-main.txt`, `.tmp-security/requirements-sdk.txt` | `-` | Fix the workflow input so Safety scans resolved versions, not specifier ranges. Draft: `ci(security): feed Safety resolved dependency versions instead of version ranges`. |

### .trivyignore audit

| CVE | Comment | Justification valid? | Action |
|-----|---------|----------------------|--------|
| `-` | `.trivyignore` is absent on HEAD. | `n/a` | No suppression audit items. Keep the file absent unless an explicit temporary exception with owner and target date becomes necessary. |

## Outcome

- The Trivy gate is behaving as configured: local current scan found `6` HIGH vulnerabilities, but all are unfixed base-image issues, so actionable count is `0` and green CI is expected.
- T04 remains adequate for the image path used by `security.yml`: the previous `setuptools` / `wheel` CVEs are no longer present in the current scan target.
- The only clear security-process gap on HEAD is the ineffective Safety job input, now tracked in `T14`.
