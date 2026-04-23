# T04 Result - Trivy verify and fallback

## Summary

- `Security Scan` run `24809054268` on 2026-04-23 failed in job `trivy`; `bandit` and `safety` were green.
- `ignore-unfixed: true` is already present in `.github/workflows/security.yml` and removes non-actionable CVE, but the image still had 3 actionable `HIGH` findings with available fixes.
- `.trivyignore` was not added. The findings were fixable in the image build itself.

## Root Cause

Local Trivy reproduction against `agentflow-api:security-scan` with `--severity HIGH,CRITICAL --ignore-unfixed` found:

1. `CVE-2026-23949` - `jaraco.context` `5.3.0` in `setuptools/_vendor`, fixed in `6.1.0`
2. `CVE-2026-24049` - `wheel` `0.45.1` in `site-packages`, fixed in `0.46.2`
3. `CVE-2026-24049` - vendored `wheel` `0.45.1` in `setuptools/_vendor`, fixed in `0.46.2`

The vulnerable packages came from the production image build in `docker-compose.prod.yml`, not from Debian OS packages. The build ended with outdated runtime packaging tooling in the final image.

## Change

- Updated the inline production image build in `docker-compose.prod.yml` to finish with:
  - `setuptools==82.0.1`
  - `wheel==0.47.0`

This replaces the vulnerable direct and vendored packaging components with versions above the fixed thresholds.

## Verification

- `docker compose -f docker-compose.prod.yml build agentflow-api` - passes
- Local Trivy scan of the rebuilt `agentflow-api:security-scan` image with `--severity HIGH,CRITICAL --ignore-unfixed --scanners vuln` - 0 actionable findings
- Probe image with the same remediation also produced 0 actionable `HIGH/CRITICAL` findings

## Status

- Local fix verified
- Remote GitHub workflow re-run on `main` is still pending the next push, so final "green on GitHub Actions" confirmation was not performed in this workspace session
