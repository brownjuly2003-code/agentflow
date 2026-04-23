# T14 - Security: make the Safety job scan resolved dependency versions

**Priority:** P1 - **Estimate:** 1-2h

## Goal

Turn the `safety` job in `.github/workflows/security.yml` into a real dependency-vulnerability check instead of a false-green run that reports `No packages found`.

## Context

- TA07 on local `HEAD a010a2d` reproduced the current workflow on `2026-04-23`.
- `safety check -r .tmp-security/requirements-main.txt -r .tmp-security/requirements-sdk.txt` returned green, but the output explicitly said `No packages found`.
- The generated requirement files currently contain version ranges copied from `pyproject.toml` / `requirements.txt` such as `fastapi>=0.111,<1`, not resolved installed package versions.
- Because Safety v2 did not resolve those ranges into concrete packages in the reproduced run, the current workflow can miss real CVEs while still staying green.

## Deliverables

1. Replace the current requirements-generation step with scan inputs that contain resolved package versions for the main app and SDK dependency sets.
2. Decide whether to resolve those versions from a temporary virtualenv, from the built production image, or by switching to a tool/input mode that can consume unresolved specifier ranges correctly.
3. Add a regression proof that fails the job when a known vulnerable package version is intentionally introduced into the scan input.
4. Document the intended dependency scope so future audits know exactly what the Safety job is scanning.

## Acceptance

- `safety check` no longer prints `No packages found`.
- The scan input files contain concrete versions rather than only specifier ranges.
- A controlled vulnerable-version test proves that the job fails when the input is wired correctly.
- The workflow remains focused on production-relevant dependencies and does not silently widen to unrelated local tooling.

## Notes

- Do not weaken the existing Trivy or Bandit gates in this task.
- Keep LF line endings.
