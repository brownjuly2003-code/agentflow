# Guarded Autopilot Dirty Worktree Preflight

Use this note when the working tree is dirty before a guarded non-dry autopilot
run. The runner blocks non-dry execution when `git status --porcelain=v1`
returns any changed file.

## Inspect Without Changing Files

Start with read-only git inspection:

```powershell
git status --short --branch
git diff --name-status
git diff --stat
git ls-files --others --exclude-standard
git diff --check
```

For a known task scope, inspect only the expected files:

```powershell
git status --short -- AGENT_STATE.md BACKLOG.md docs/operations/
git diff -- AGENT_STATE.md BACKLOG.md docs/operations/
```

Do not run `git checkout --`, `git reset --hard`, `git clean`, or delete files
to make the tree clean. Preserve user and parallel-session work.

## When To Stop

Stop before a guarded non-dry autopilot run when any of these are true:

- Changed files are outside the current backlog item's allowed paths.
- Shared files such as `AGENT_STATE.md`, `BACKLOG.md`, router indexes,
  generated contracts, package manifests, or configuration files changed for an
  unrelated task.
- Source, tests, SDK, deploy, Terraform, secret, or generated files changed but
  the current task is documentation-only.
- The dirty state includes files you cannot confidently attribute to the
  current task.

Record the blocker in `AGENT_STATE.md` or `BACKLOG.md` instead of merging,
reverting, or deleting unrelated work.

## Retry Preflight

After the dirty state is resolved by the owner of those changes, rerun:

```powershell
git status --short --branch
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

Only start a guarded non-dry autopilot run when the intended task has an
explicit allowed-paths scope and the remaining worktree state is understood.

## Forbidden Operations

Do not use dirty-worktree preflight to justify deploy, publish, Terraform,
secret, scheduler install, external account, cleanup, revert, commit, or push
operations.
