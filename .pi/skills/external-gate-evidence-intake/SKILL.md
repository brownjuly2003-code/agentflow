---
name: external-gate-evidence-intake
description: "Use for AgentFlow release-readiness follow-ups that involve external gate evidence: AWS OIDC Terraform apply, production CDC onboarding, PMF/pricing evidence, public production-hardware benchmarks, external pen-test attestation, or legacy npm NPM_TOKEN revocation. Guides evidence intake without marking gates complete from local repo analysis alone."
---

# External Gate Evidence Intake

## Purpose

Use this skill when an AgentFlow operator asks to advance a blocked external
release gate or account-control follow-up. The goal is to collect and record
reviewable evidence, not to infer completion from local repository state.

Never mark an external gate complete unless the item-specific required fields
are supplied by a real operator/owner and pass the no-go checks in
`docs/operations/external-gate-evidence-intake.md`.

## Start

Run these checks first:

```powershell
git status --short
git rev-parse --short HEAD
Get-Content docs\release-readiness.md
Get-Content docs\operations\external-gate-evidence-intake.md
```

If files for the selected gate are already modified, stop and report the
conflict before editing.

## Choose One Gate

Work on exactly one item at a time:

- AWS OIDC Terraform apply readiness:
  `docs/operations/aws-oidc-setup.md`
- Production CDC source onboarding:
  `docs/operations/cdc-production-onboarding.md`
- PMF and pricing evidence:
  `docs/customer-discovery-tracker.md` and
  `docs/pricing-validation-plan.md`
- Public production-hardware benchmark:
  `docs/perf/public-production-hardware-benchmark-plan.md`
- External pen-test attestation:
  `docs/operations/external-pen-test-attestation-handoff.md`
- Legacy npm `NPM_TOKEN` revocation:
  `docs/publication-checklist.md`

Prefer the first item that has real owner/operator evidence available. If no
item has evidence, tighten the handoff or intake checklist instead of changing
gate status.

## Evidence Rules

For the selected gate:

1. Read the matching section in
   `docs/operations/external-gate-evidence-intake.md`.
2. Confirm every required owner-provided field is present.
3. Confirm linked artifacts are durable and reviewable.
4. Confirm secrets, tokens, raw customer data, private account IDs, and private
   hostnames are redacted before linking from the repo.
5. Check every explicit no-go condition.
6. Check every insufficient-evidence example.
7. Only then add an acceptance record or update `docs/release-readiness.md`.

Local dry runs, repository analysis, modelled research, CLI trust readback, or
green historical CI runs are not enough unless the intake section explicitly
accepts them for the claimed state.

## npm Token Boundary

For legacy npm `NPM_TOKEN` revocation:

- Use the `npm-recovery-codes` guard before any OTP-gated npm action.
- Do not print OTPs, recovery codes, npm tokens, auth URLs, cookies, or token
  screenshots that expose secret values.
- Do not consume a recovery code unless at least two usable recovery codes will
  remain afterwards.
- Do not treat the green `2c72387` `publish-npm.yml` run as revocation proof; it
  published legacy `@uedomskikh/agentflow-client` with `NODE_AUTH_TOKEN`.
- Required proof must include a successful trusted-publish workflow run for
  `@yuliaedomskikh/agentflow-client`, repository secret audit, npm token audit,
  recovery-code reserve confirmation, and review owner.

## Update Pattern

When evidence passes intake:

- Update only the item-specific handoff and, if needed,
  `docs/release-readiness.md`.
- Use the acceptance record template from
  `docs/operations/external-gate-evidence-intake.md`.
- Keep raw external artifacts in secure systems or redacted evidence paths; do
  not paste secrets or customer data into the repo.

When evidence does not pass intake:

- Keep the gate blocked.
- Record the missing owner fields or no-go condition only if it reduces future
  ambiguity.
- Do not convert a blocked external gate into a local TODO marked complete.

## Verification

After any repo change:

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest -p no:schemathesis -q --basetemp .tmp\<task-basetemp> -o cache_dir=.tmp\<task-cache>
```

Commit only if explicitly asked, tests pass, and `git status --short` contains
only expected files. Use explicit pathspecs for `git add`.
