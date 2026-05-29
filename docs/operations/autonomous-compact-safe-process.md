# Autonomous Compact-Safe Process

This note defines how an agent should continue work without asking the operator
for routine direction, while avoiding stale compact context, repeated blocked
work, and fabricated external evidence.

## Operating Rule

When the operator requests autonomous work, the agent owns local tactical
decisions:

- pick the next safe atomic item;
- run the narrowest useful diagnostic;
- make scoped local edits;
- run relevant no-Docker verification on this Windows host;
- create a local commit after a verified atomic item;
- continue to the next safe item without asking for confirmation.

Do not ask "what next" while a safe local candidate exists.

## Durable Context Recovery

If chat context is compacted, incomplete, contradictory, or stale, rebuild from
checked-in and runtime state instead of asking the operator for a recap.

Read in this order:

1. `AGENT_STATE.md`
2. `docs/SESSION_HANDOFF.md`
3. `docs/operations/local-verification-matrix.md`
4. `AUTOPILOT.md`
5. `BACKLOG.md`
6. `.autopilot/BLOCKED.md`, when present

Then run:

```powershell
git status --short --branch --untracked-files=no
git rev-parse --short HEAD
git log --oneline --left-right main...origin/main
```

Use current repository evidence over remembered chat state.

## Candidate Selection

Choose the first safe candidate in this order:

1. Current dirty WIP closure.
2. Failed or blocked verification diagnostics with a local next step.
3. A named PLAN/BACKLOG item that can be completed without Docker, secrets,
   deploys, paid services, production data, or live external accounts.
4. A narrow uncovered or failing test that has a local no-Docker verification.
5. A documented ops finding with a concrete file-level fix.

Do not choose work whose only effect is updating timestamps, HEAD hashes,
branch-ahead counts, latest-commit lists, or handoff prose.

## Anti-Repeat Check

Before starting an item, compare it with the most recent completed or blocked
item family in `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`, `BACKLOG.md`, and
`.autopilot/BLOCKED.md`.

Do not repeat the same family unless one of these is true:

- new owner-provided evidence exists;
- a fresh command failed or timed out and has a local diagnostic path;
- the item is a distinct named atomic task with different files or different
  verification;
- dirty WIP from that family must be closed.

If a gate is externally blocked, record the non-secret evidence once and move to
another safe local candidate. If no candidate remains, stop with the blocker
instead of rechecking the same gate again.

## External And Admin Gates

For AWS, Terraform apply, production CDC, PMF/pricing, production-hardware
benchmarks, external pen-test, immutable retention, publishing, releases,
deploys, scheduler changes, and secret/account work:

- do not invent evidence;
- do not print secrets;
- do not enable workflows or run apply/deploy/publish commands without the
  exact required authority and artifacts;
- delegate to an admin-capable tool or agent when available;
- integrate only verified, non-secret facts returned by that delegate.

If the delegate reports no real evidence, keep the gate blocked.

## Local Commit Policy

Local commits are allowed after a verified atomic item when the dirty set is
scoped and intentional.

Before committing:

```powershell
git status --short --branch --untracked-files=no
git diff --check
```

Stage only intended paths:

```powershell
git add <path> <path>
git commit -m "<type>: <summary>"
```

Do not use `git add -A` or `git add .`.

## Remote Boundary

The operator has granted standing authorization for ordinary
`git push origin main` from a human-agent autonomous session. Run it without
asking again only after:

- `git status --short --branch --untracked-files=no` shows a clean tracked
  worktree and no unexpected branch divergence;
- `git diff --check` passes;
- the commits being pushed were created or reviewed in this autonomous session.

This authorization is narrow. Force-push, pushing other branches or tags,
deploy, release, package publish, Terraform apply, scheduler/env changes,
destructive git operations, stash drops, and secret/account work remain remote
or destructive boundaries unless the latest operator instruction explicitly
names that action and target.

If any non-authorized boundary is reached, finish all safe local preparation
first. Then record the exact blocked command and the missing authority. Do not
keep asking for the same boundary decision on every turn.

## Windows No-Docker Rule

This workstation is no-Docker. Do not start Docker Desktop, `docker compose`,
`docker build`, kind, Helm live validation, chaos tests, or Docker-dependent
full pytest here. Use `SKIP_DOCKER_TESTS=1` for broad local pytest and mark
Docker-heavy evidence as Mac/CI-pending.
