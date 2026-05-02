# Next Session Two-Agent Plan

## Current State

- Branch: `main`, ahead of `origin/main` by 9 commits.
- HEAD: `dbc4a1e docs: define pmf batch decision gates`.
- Working tree was clean after the last commit.
- Do not push unless the user explicitly asks.
- Do not touch `ttt.txt` or local secret notes.

## Goal

Continue AgentFlow post-release work by moving from PMF planning to execution,
while keeping release gates and registry/infra follow-ups explicit.

## Coordinator Tasks

- [ ] Confirm whether the user wants `git push` now.
  Verify: explicit user approval before running push.
- [ ] If pushing, run pre-push gates first:
  `python -m pytest -p no:schemathesis`, `npm run test:unit`, and
  `npm run typecheck`.
  Verify: all commands exit 0.
- [ ] Keep sub-agent write scopes separate.
  Verify: Agent 1 writes only customer-discovery docs; Agent 2 writes only
  release/pricing/infra status docs unless coordinator changes scope.

## Agent 1: PMF Discovery Execution

Owns: `docs/customer-discovery-tracker.md` and any user-approved outreach notes.

- [ ] Fill the first 15 candidate slots with real names, teams, sources, and
  qualification reasons.
  Verify: `Batch Funnel Metrics` named candidates sourced reaches `15`.
- [ ] Select the first 10 candidates for outreach across at least 3 target
  profiles.
  Verify: no more than 2 interviews are scheduled from the same profile before
  all 5 slots have at least one credible candidate.
- [ ] Draft or refine outreach messages only after candidates are known.
  Verify: each message maps to a concrete target slot and qualification reason.
- [ ] After calls happen, record only valid interviews against the 5-call batch.
  Verify: each counted interview passes the `Interview Quality Bar`.

## Agent 2: Pricing And Release Gate Tracking

Owns: `docs/pricing-validation-plan.md` and `docs/release-readiness.md`.

- [ ] Keep pricing uncommitted until real interview evidence exists.
  Verify: no public price points, tiers, or pricing-page copy are added.
- [ ] After each valid interview, extract pricing evidence into the pricing plan:
  budget owner, replaceable cost, value metric reaction, pilot shape, and pricing
  risk.
  Verify: evidence maps back to interview notes in the tracker.
- [ ] Refresh release-readiness only when a gate actually changes.
  Verify: PMF remains open until 5 valid interviews are completed and scored.
- [ ] Track non-PMF release gates separately: AWS OIDC role, production CDC
  onboarding, legacy `NPM_TOKEN` revocation after trusted publish, external
  pen-test attestation, public production benchmark, and first paying customers.
  Verify: unchecked gates are not described as done.

## Final Verification

- [ ] Run `git status --short` and confirm only intended files changed.
- [ ] Run `git diff --check`.
- [ ] For docs-only changes, run full repo gates before commit if committing:
  backend pytest, TypeScript unit tests, and TypeScript typecheck.
- [ ] Commit with explicit pathspecs only.
  Verify: no `git add -A` or `git add .`.
