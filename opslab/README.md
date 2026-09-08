# OpsLab — dormant benchmark distribution

`agentflow-opslab` is a **separate distribution that lives in this repository
but is not part of AgentFlow's build, gates, or releases**. It currently holds
one thing: a package boundary and the structural test that defends it. There is
no implementation behind it yet.

This page exists because the directory is otherwise unexplainable: audit FB-16
found eight tracked files that no `pyproject.toml`, workflow, or documentation
page referenced, which reads either as abandoned work or as a live component
someone forgot to wire up. It is neither.

## What it is

A transport-neutral benchmark core for operational AI agents, kept in its own
distribution so its contracts can never quietly acquire a dependency on the
serving runtime. `opslab/pyproject.toml` declares `agentflow-opslab` 0.1.0 with
its own build backend, dependency set (empty), Ruff configuration, and pytest
paths.

Tracked contents:

| Path | What it holds |
|------|---------------|
| `src/agentflow_opslab/__init__.py` | version marker |
| `src/agentflow_opslab/domain/` | pure values, state machines, invariants — empty shell |
| `src/agentflow_opslab/contracts/` | schema-bound DTOs and the version registry — empty shell |
| `src/agentflow_opslab/ports/` | narrow capabilities implemented only at adapters — empty shell |
| `src/agentflow_opslab/py.typed` | typing marker |
| `tests/test_package_boundary.py` | the structural contract, below |
| `pyproject.toml`, `.gitignore` | the isolated distribution's own configuration |

## The contract it already enforces

`tests/test_package_boundary.py` is three tests:

1. the distribution metadata names `agentflow-opslab` and packages only
   `src/agentflow_opslab`;
2. importing `agentflow_opslab` in an isolated interpreter (`python -I`) loads
   it from this source root and pulls in neither `agentflow_runtime` nor the
   deprecated `src` shim;
3. no module under the core areas imports `agentflow_runtime`, `src`,
   `fastapi`, `duckdb`, `confluent_kafka`, `httpx`, `mcp`, or `a2a`.

## Status: step 1 of an archived plan

The design and the ordered work list are in
[`docs/archive/plans/plan-26-opslab-first-draft.md`](../docs/archive/plans/plan-26-opslab-first-draft.md).
Step 1 — *isolate the package boundary* — was completed on 2026-08-26 in commit
`fff2dd3` and is what this directory is. Steps 2 and onward (the normative
contract kernel, the `oversell-1` scenario, deterministic replay) were never
started, and that plan now lives in the documentation archive.

## What is deliberately not wired up

Nothing in the root project builds, ships, or checks this code:

- the runtime wheel's `only-include` covers `src/agentflow_runtime` and
  `packaging/src_shim/src` only, so `agentflow_opslab` cannot land in a
  published artifact;
- the CI `lint` job runs Ruff over `src/ tests/ scripts/ sdk/ integrations/
  warehouse/` and mypy over `src/` — neither reaches here;
- the CI `test-unit` job runs `tests/unit` and `tests/property`, so **the three
  boundary tests above never execute in CI**.

Run them by hand from the repository root:

```bash
python -m pytest opslab/tests
```

Last run 2026-09-07 on `f4b5f0b`: `3 passed`.

## The open decision

Two coherent endings, both the owner's to pick:

- **Continue.** Step 2 of the archived plan already specifies the next move —
  attach nested gates to root CI so this boundary is enforced rather than
  merely asserted — and that is the point at which the "not wired up" section
  above stops being true.
- **Delete.** Removing `opslab/` costs one revert of `fff2dd3` and loses a
  boundary that has never been depended on.

Leaving it dormant is fine; leaving it *unexplained* was the finding.
`tests/unit/test_opslab_isolation.py` keeps the isolation claims on this page
true.
