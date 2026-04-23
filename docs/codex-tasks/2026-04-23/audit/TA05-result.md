# TA05 result

- Snapshot: local `HEAD a010a2d` on `main` as of `2026-04-23`.
- Working tree was already dirty with ignored and untracked local outputs; the report separates tracked Git-tree findings from local runtime state.

## Stale code + artifacts scan

### Unused modules (vulture, confidence >=80)

| File | Symbol | Recommendation |
|------|--------|----------------|
| `tests/unit/test_cli.py:21` | `exc_type`, `tb` | False positive. `_DummyStreamResponse.__exit__` must keep the full context-manager signature, so no cleanup is recommended. |

No actionable unused modules or dead Python symbols remained after manual filtering.

### Unused imports (ruff F401/F841)

| File:Line | Symbol | Recommendation |
|-----------|--------|----------------|
| `-` | `-` | `ruff check src tests --select F401,F841 --output-format concise` returned clean output. |

### Orphan test files

| Test | Imports missing `src/` module | Action |
|------|-------------------------------|--------|
| `-` | `-` | AST scan of `tests/**/*.py` found no imports of missing `src` modules. |

### Runtime artifacts in tree

| File | Size | Action (delete/gitignore) |
|------|------|---------------------------|
| `-` | `-` | `git ls-files` found no tracked `*.duckdb`, `*.duckdb.wal`, `*.cache`, `*.tmp`, `*.log`, or `*.pid` artifacts. `git ls-files -ci --exclude-standard` also returned empty output. |

### Branches / tags

| Ref | Finding | Action |
|-----|---------|--------|
| `branches` | Only `main`, `origin/main`, and `origin/HEAD -> origin/main` exist. | No stale branch cleanup needed. |
| `tags` | `v1.0.0` and `v1.0.1` are present. | No stale tag action needed. |

### Stale docs

| Path | Last modified | Recommendation (archive/delete/keep) |
|------|---------------|--------------------------------------|
| `docs/plans/codex-archive/*.md` | `2026-04-10` to `2026-04-20` | Keep. All files are newer than 30 days and planning docs are explicitly exempt from cleanup in this task. |
| `docs/codex-tasks/2026-04-22/` | `2026-04-22` | Keep. This sprint is recent context, and TA05 notes explicitly say not to archive it. |

### Untracked / .gitignored

| Path | Note |
|------|------|
| `agentflow_api.duckdb` | Ignored runtime DuckDB file at repo root, size `2109440` bytes, last modified `2026-04-23 07:36`. `git check-ignore -v` currently resolves it to `.gitignore:72` `AgentFlow*`, so it is hidden by the broad wildcard rather than an explicit DuckDB/runtime rule. |
| `warehouse/agentflow/` | Ignored local Iceberg warehouse data/metadata. `git check-ignore -v` also resolves this path to `.gitignore:72` `AgentFlow*`, which is broader than intended. Follow-up ticket: `docs/codex-tasks/2026-04-24/T13-gitignore-agentflow-pattern-hardening.md`. |
| `.coverage`, `coverage.xml` | Ignored coverage outputs from local verification runs. |
| `.artifacts/`, `.dora/`, `.iceberg/`, `.tmp/`, `mutants/` | Ignored generated runtime/test artifacts; expected local state. |
| `docs/codex-tasks/2026-04-23/audit/TA01-result.md` | Untracked parallel-task deliverable; not stale. |
| `docs/codex-tasks/2026-04-24/T10-*.md`, `T11-*.md`, `T12-*.md` | Untracked follow-up tickets from TA01; pending add/commit, not stale. |

Standard `__pycache__/`, `node_modules/`, `dist/`, and virtual-environment directories were also present and correctly ignored, so they are omitted from the table for brevity.

## Outcome

- No actionable dead code, orphan tests, tracked runtime artifacts, or stale refs were found in this scan.
- One actionable hygiene follow-up was identified: narrow the `.gitignore` wildcard `AgentFlow*` and replace it with explicit runtime/session-note rules so local warehouse state is hidden intentionally rather than accidentally.
