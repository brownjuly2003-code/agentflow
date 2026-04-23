# T13 - Gitignore: narrow the `AgentFlow*` wildcard and ignore runtime state explicitly

**Priority:** P2 - **Estimate:** 1-2h

## Goal

Make `.gitignore` hide local runtime warehouse outputs through explicit rules instead of the broad `AgentFlow*` wildcard that currently suppresses `warehouse/agentflow/` on Windows.

## Context

- TA05 on local `HEAD a010a2d` found that `git check-ignore -v warehouse/agentflow` resolves to `.gitignore:72` `AgentFlow*`.
- That wildcard lives in the "Session notes" block, but it is case-insensitive on the current platform and matches path segments named `agentflow` outside the repo root.
- The same block already needs carve-outs for `sdk/agentflow/**`, `integrations/agentflow_integrations/**`, and `helm/agentflow/**`, which is a signal that the rule is too broad.
- Local runtime outputs such as `agentflow_api.duckdb` should stay ignored, but the ignore reason should be explicit and auditable.

## Deliverables

1. Replace the broad session-note wildcard with anchored root-level patterns for the actual temporary note files that should stay ignored.
2. Add an explicit ignore rule for the local warehouse/runtime path if `warehouse/agentflow/` is intended to remain untracked.
3. Re-run `git check-ignore -v` for:
   - `warehouse/agentflow`
   - `sdk/agentflow`
   - `integrations/agentflow_integrations`
   - `helm/agentflow`
   - `agentflow_api.duckdb`
4. Document the final ignore behavior so TA10 can distinguish intentional runtime state from accidentally hidden files.

## Acceptance

- `warehouse/agentflow/` is ignored by an explicit runtime/data rule, not by the generic `AgentFlow*` wildcard.
- `sdk/agentflow/`, `integrations/agentflow_integrations/`, and `helm/agentflow/` remain visible without depending on fragile exception sprawl.
- Repo-root session notes that truly should stay local are still ignored.

## Notes

- Do not delete local warehouse or DuckDB state in this task.
- Keep LF line endings.
