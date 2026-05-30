# Next Session Autonomous Local Plan

## Goal

Restore the repository from durable state, close any current dirty WIP first,
and continue only if there is a safe local atomic task. This Windows workstation
is no-Docker; Docker-heavy verification stays Mac/CI-pending unless explicitly
assigned to the iMac path.

## Start Checklist

- [ ] Run `git status --short --branch --untracked-files=no`.
- [ ] Run `git rev-parse HEAD` and `git log --oneline -10`.
- [ ] Check open PRs with `gh pr list --state open`.
- [ ] Check current `main` workflows with `gh run list --branch main --limit 12`.
- [ ] Read `AGENT_STATE.md`.
- [ ] Read `docs/SESSION_HANDOFF.md`.
- [ ] Read `docs/operations/local-verification-matrix.md`.
- [ ] Read `AUTOPILOT.md`.
- [ ] Read `docs/operations/autonomous-compact-safe-process.md`.
- [ ] Read `BACKLOG.md`.
- [ ] Read `.autopilot/BLOCKED.md` if it exists.

## Decision Rules

- If the worktree is dirty, inspect those files first and close only the
  current WIP unless there is an unrelated dirty-file conflict.
- If a workflow is failed or pending for the current HEAD, diagnose that exact
  run before selecting new work. Use no-Docker local checks on Windows.
- If a PR is open, handle only safe local review/test/docs work unless merge,
  branch-protection, deploy, release, or secret boundaries are explicitly
  authorized.
- If the only known item is promoting `build-smoke` to a required status check,
  stop unless the operator explicitly authorizes the GitHub branch-protection
  change and target.
- If the only known items are AWS/Terraform, paid services, secrets,
  production/deploy/publish, external pen-test, production CDC, production
  benchmark, or PMF/pricing evidence, record the blocker and do not simulate
  real evidence.
- If there is a new bounded local docs/code/test task, make the smallest scoped
  change, run relevant no-Docker verification, commit with explicit pathspecs,
  and push `origin main` only after clean status and `git diff --check`.

## Current Safe State

- Current verified HEAD before this plan was written: `0759fc6`.
- Open PRs: none.
- GitHub workflows for `0759fc6`: CI, Security Scan, Load Test, E2E Tests,
  Staging Deploy, and Contract Tests all green.
- Backlog tasks 0-17 and 23-24 are done.
- Task 18 AWS/Terraform is out of scope by budget/payment constraint.
- Tasks 19-22 need real owner-provided external evidence.
- The `build-smoke` required-check promotion remains a remote/admin boundary.

## Done When

The next session should end with either a verified scoped commit pushed to
`origin/main` and green workflows, or a clean worktree plus a durable note that
no safe local candidate exists without new evidence or explicit authorization.
