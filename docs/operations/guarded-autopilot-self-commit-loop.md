# Guarded Autopilot Self-Commit Loop

Use this note for the default local guarded backlog loop when a bounded task
explicitly allows a local commit. The loop may create a local commit through
`scripts/autopilot.ps1 -Commit`, but it must never push.

## Preconditions

Start only when all of these are true:

- The working tree is clean before the non-dry run starts.
- `.autopilot/NEXT_TASK.md` contains the exact gate `commit allowed: yes`.
- `.autopilot/allowed-paths.txt` lists every file or directory the task may
  change.
- `.autopilot/commit-message.txt` exists and contains the intended local commit
  message.
- The task excludes deploy, publish, Terraform apply, production database,
  scheduler install, external account, paid API, cleanup, revert, push,
  product-code, and secret operations.

## Inspect Local State

Run these read-only checks from the repo root before any non-dry commit run:

```powershell
git status --short --branch
Get-Content .autopilot\NEXT_TASK.md
Get-Content .autopilot\allowed-paths.txt
Get-Content .autopilot\commit-message.txt
git diff --check
```

Stop if the tree is dirty, the task does not include `commit allowed: yes`, the
allowed paths are missing or too broad, or the commit message is missing.

## Dry Run

Use dry-run mode as the local preflight for every guarded backlog loop:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

The dry run checks PAUSE and BLOCKED state, confirms the local `pi` and `codex`
commands are available, and runs `git status --short -uno` plus
`git diff --check`. It does not authorize deploy, publish, Terraform, secret,
scheduler, external account, paid API, cleanup, revert, push, or product-code
work.

## Non-Dry Commit Mode

Run commit mode only after the preconditions and dry run pass:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Commit
```

The runner requires a clean worktree at startup. After planner and executor
finish, it validates every changed path against `.autopilot/allowed-paths.txt`.
For commit-enabled runs, it stages only the verified changed files with an
explicit pathspec and validates the staged diff before committing:

```powershell
git add -- <verified-changed-files>
git diff --cached --check
git commit -F .autopilot\commit-message.txt
```

Do not replace this with `git add .` or `git add -A`.

## Post-Run Verification

Inspect the result locally after the runner exits:

```powershell
git status --short --branch
git log -1 --oneline
git show --stat --oneline --name-only HEAD
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

If the run leaves uncommitted changes, reports a blocker, or changes files
outside `.autopilot/allowed-paths.txt`, stop and preserve the evidence instead
of cleaning up, reverting, pushing, deploying, publishing, running Terraform,
installing a scheduler, using external accounts, calling paid APIs, touching
production data, editing product code, or reading secrets.

## Push Boundary

`git push` remains outside the guarded local loop because it changes remote
state and may trigger CI, deploy, publish, external account, or secret-backed
workflows. A push requires a separate explicit operator decision after the local
commit has been inspected.
