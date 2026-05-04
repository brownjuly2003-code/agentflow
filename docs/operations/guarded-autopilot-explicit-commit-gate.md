# Guarded Autopilot Explicit Commit Gate

Use `scripts/autopilot.ps1 -Commit` only for a bounded task that explicitly
allows a commit. The runner may commit locally, but it must never push.

## Commit Preconditions

All of these must be true before starting a commit-enabled run:

- The working tree is clean before the non-dry run starts.
- `.autopilot/NEXT_TASK.md` says `commit allowed: yes`.
- `.autopilot/commit-message.txt` exists and contains the intended commit
  message.
- `.autopilot/allowed-paths.txt` lists every file or directory the task may
  change.
- The task does not require deploy, publish, Terraform, secrets, scheduler
  install, external accounts, paid services, or production data.

## Preflight

Run the local preflight first:

```powershell
git status --short --branch
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

If the dry run reports PAUSE, BLOCKED, missing local commands, or an unexpected
dirty tree, resolve that state before considering `-Commit`.

## Required Gates

The runner always runs `git diff --check`. When changed paths require them and
the tools are available locally, it also runs the relevant gates from the local
verification matrix:

```powershell
python -m pytest -p no:schemathesis
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/
python -m mypy src/
Push-Location sdk-ts; npm run typecheck; npm run test:unit; npm run build; Pop-Location
```

For commit-enabled runs, the runner also validates the staged diff with:

```powershell
git diff --cached --check
```

## Commit Behavior

The runner commits only after validating changed files against
`.autopilot/allowed-paths.txt`. It stages files with an explicit pathspec from
the verified changed-file list:

```powershell
git add -- <verified-changed-files>
git commit -F .autopilot\commit-message.txt
```

Do not replace this with `git add .` or `git add -A`. Do not run `git push` from
the guarded autopilot flow.

## Command

Use this only after the preconditions and preflight are satisfied:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Commit
```
