# Guarded Autopilot Allowed Paths

Use this note before a non-dry guarded autopilot run when the next backlog item
has a bounded file scope. The goal is to make the runner's path gate explicit
before execution.

## Scope File

Create `.autopilot/allowed-paths.txt` with one repo-relative file or directory
per line. Empty lines and lines beginning with `#` are ignored. The `.autopilot/`
directory is ignored local runtime state and should not be committed.

Example for a documentation-only task:

```text
docs/operations/
AGENT_STATE.md
BACKLOG.md
```

A changed file is allowed only when it exactly matches one of these entries or
is inside a listed directory.

## Preflight

Run these checks before a guarded non-dry run:

```powershell
git status --short --branch
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

The dry run should report that the PAUSE and BLOCKED protocols are OK, that the
allowed-paths protocol requires `.autopilot/allowed-paths.txt` before execution,
and that the local `pi` and `codex` commands are available.

## Forbidden Operations

Do not include deploy, publish, Terraform, secret, scheduler install, or
external account work in the allowed paths flow. If a backlog item needs one of
those operations, stop and record the blocker instead of running autopilot.
