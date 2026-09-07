# DE_project Rules

## Durable State and Autonomous Continuation
- On a new session, resume, compaction, stale context, or contradiction, rebuild from `git status` and these files when present: `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`, `docs/operations/local-verification-matrix.md`, `AUTOPILOT.md`, `docs/operations/autonomous-compact-safe-process.md`, `BACKLOG.md`, `.autopilot/BLOCKED.md`.
- If remembered work is already finished, impossible, or contradicted by disk state, stop pursuing it and choose another safe atomic item.
- Candidate order is dirty WIP, failed or blocked verification diagnostics, PLAN/Next Work, narrow failing or uncovered tests, then documented operations findings.
- A real external blocker ends that atomic item. Record non-secret evidence and continue only with an independent safe item.
- A single verification or acceptance check may have at most **five full attempts per named slice**, counted `1/5` through `5/5`; the initial run is `1/5`. After each failed or timed-out attempt, another full attempt is allowed only after a new narrowed diagnostic hypothesis or a relevant corrective change. Raw unchanged retries are forbidden. If attempt `5/5` fails or times out, end the slice for the turn and report it.

## Verification Hosts
- Keep local Windows Python processes below 1 GiB. Use narrow checks and rely on `D:\SystemState\PythonMemoryGuard\python-memory-guard.ps1`.
- Run Docker-heavy verification, jobs likely to exceed 1 GiB, and macOS diagnostics through SSH alias `deproject-mac`; the Mac checkout is `/Users/julia/agentflow-docker-check`.
- Non-secret Mac context belongs in `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`, and `docs/operations/local-verification-matrix.md`.
- Never print, commit, or copy SSH keys, passwords, tokens, recovery codes, or other secrets into project files, logs, PRs, or chat.
