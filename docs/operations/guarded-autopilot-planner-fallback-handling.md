# Guarded Autopilot Planner Fallback Handling

Use this note when a guarded autopilot run reports that the `pi` planner failed
and the runner is falling back to the `codex` planner. The fallback is local
planner continuity only; it does not expand the task scope.

## Interpretation

The runner starts with `pi` for planning. If `pi` exits nonzero, the runner logs
the failure and retries the same planner prompt with `codex`. Treat this as a
local tooling or authentication issue for `pi`, not as permission to inspect,
print, rotate, request, or recover API keys, tokens, environment secrets,
cookies, recovery codes, credentials, browser sessions, password-manager
entries, or account settings.

Acceptable local evidence is limited to the runner log, the selected task, the
allowed paths, and any blocker report. Authentication repair, credential
rotation, account login, npm ownership, paid API, or external account work
requires a separate explicit operator task.

## Read-Only Inspection

After a fallback or planner failure, inspect only local runtime evidence from
the repo root:

```powershell
git status --short --branch
Get-ChildItem .autopilot\logs -Force | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,Length,LastWriteTime
$latest = Get-ChildItem .autopilot\logs -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) { Get-Content $latest.FullName -Tail 120 }
Get-Content .autopilot\NEXT_TASK.md
Get-Content .autopilot\allowed-paths.txt
if (Test-Path .autopilot\BLOCKED.md) { Get-Content .autopilot\BLOCKED.md }
git diff --check
```

If `.autopilot/NEXT_TASK.md` or `.autopilot/allowed-paths.txt` is missing, stop
and record the planner failure. Do not reconstruct task scope from the current
diff, shell history, environment variables, credential files, or account state.

## Commit Boundary

Local self-commit mode is allowed only through the explicit gate and the
runner's allowed-path validation. Before any commit-enabled run, all of these
must be true:

- `.autopilot/NEXT_TASK.md` contains the exact gate `commit allowed: yes`.
- `.autopilot/allowed-paths.txt` lists the complete bounded write scope.
- The working tree is clean before the runner starts.
- Required verification for the selected task can run locally.
- The task excludes secret, deploy, publish, Terraform apply, scheduler,
  external account, paid API, cleanup, revert, push, production database,
  production data, and product-code work.

Use dry-run first:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

Run commit mode only after the dry run passes and the explicit gate is present:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Commit
```

The runner validates changed files against `.autopilot/allowed-paths.txt` and
uses explicit pathspec staging before a local commit. Do not replace that flow
with `git add .`, `git add -A`, manual cleanup, revert, push, deploy, publish,
Terraform apply, scheduler install, external account work, paid APIs, product
code edits, production database access, production data access, or secret
operations.
