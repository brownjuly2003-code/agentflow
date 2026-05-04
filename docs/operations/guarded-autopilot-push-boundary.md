# Guarded Autopilot Push Boundary

Use this note after a guarded autopilot run has produced one or more local
commits. The local loop may inspect commits and changed files, but any remote
push is a separate operator decision.

## Local Boundary

`scripts/autopilot.ps1 -Commit` is limited to local repository state. It may
create a local commit only after the explicit `commit allowed: yes` gate,
required verification, and allowed-path validation. It must not push,
force-push, deploy, publish, apply Terraform, install a scheduler, use external
accounts, call paid APIs, touch production data, change remotes, or read
secrets.

Treat push readiness as a handoff question, not as part of the guarded
autopilot loop. A clean local commit does not authorize `git push`.

## Read-Only Inspection

Run these commands from the repo root to inspect locally known branch state,
recent commits, and changed files without pushing or changing remotes:

```powershell
git status --short --branch
git branch -vv
git log --oneline --decorate -10

$upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>$null
if ($LASTEXITCODE -eq 0) {
    git rev-list --left-right --count "HEAD...$upstream"
    git log --oneline --decorate "$upstream..HEAD"
    git diff --name-status "$upstream..HEAD"
} else {
    "No upstream is configured for the current branch."
}

git diff --name-status
git diff --cached --name-status
```

These commands use the locally known upstream reference. If the upstream state
may be stale, stop and ask the operator whether a separate network-aware fetch
or push decision is intended. Do not fetch credentials, inspect environment
secrets, change remote URLs, or infer permission to push from local status
output.

## Stop Before Push

Stop and ask for an explicit operator decision before `git push` whenever any
of these are true:

- The branch is ahead of its upstream, has no upstream, is behind, or has
  diverged.
- The push would require `--force`, `--force-with-lease`, remote changes, or
  branch creation.
- The local commits touch deploy, publish, Terraform, production database,
  production data, scheduler, external account, paid API, secret, cleanup,
  revert, or product-code areas that were outside the completed task.
- The push may trigger CI, deployment, package publishing, infrastructure
  changes, or secret-backed workflows.
- The working tree still has uncommitted changes, a blocker report, or changes
  outside `.autopilot/allowed-paths.txt`.

The operator decision must name the remote, branch, and push intent. Without
that explicit decision, preserve the local evidence and do not push.
