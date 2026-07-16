# P2-6 — Runtime namespace: `src` → `agentflow_runtime`

> Plan + **Phase 0 inventory (done 2026-07-17)**. Do **not** start Phase 1
> (tree move / dual import) until a breaking release window is scheduled.
> Source of the finding: `audit_gpt_11_07_26.md` §P2-6.

## Problem

| Today | Risk |
|-------|------|
| Distribution name `agentflow-runtime` | Fine |
| Wheel packages top-level **`src`** (`[tool.hatch.build.targets.wheel] packages = ["src"]`) | Namespace collision with any other project that also ships `src`; non-idiomatic public import (`from src.serving…`) |
| Import surface used everywhere in-repo | `src.*` in app code, tests, Docker/helm command lines, Flink image layout, docs |

## Target

- Installable package name: **`agentflow_runtime`** (import path matches
  distribution intent; aligns with wheel evidence paths in
  `docs/runbooks/release-rollback.md`).
- Deprecation window: keep a top-level **`src`** shim that re-exports or
  warns, then remove in N+1.
- No change to distribution name `agentflow-runtime` unless a separate
  rename is decided.

## Non-goals (this plan)

- Renaming `sdk/agentflow` or `sdk-ts` packages.
- Making `agentflow-integrations` publishable (separate P2-6 bullet —
  either first-class CI/publish or explicit “internal”).
- Full monorepo re-layout.

## Migration phases

### Phase 0 — inventory (no code move)

1. List all runtime entrypoints that hardcode `src.`:
   - process modules: `python -m src.processing.bridge_consumer`,
     `src.serving.api.main:app` (uvicorn / helm / staging Dockerfile)
   - tests / mypy `packages=["src"]` if any
   - docs and scripts
2. Confirm hatch config: today only `packages = ["src"]` under
   `[tool.hatch.build.targets.wheel]`.
3. Build a wheel and record `unzip -l dist/*.whl | head` so the before/after
   tree is evidence-backed.

### Phase 1 — physical package + dual import (breaking-prep)

1. Move or package-dir map `src/` content so imports are
   `agentflow_runtime.…` while **source tree stays reviewable** (prefer
   `src/agentflow_runtime/` layout *or* hatch `packages` map — pick one in
   implementation PR, not both ad hoc).
2. Provide `src/__init__.py` shim:
   - re-export / path-hook / `import agentflow_runtime as …` pattern that
     keeps `import src.serving…` working for one minor line.
   - optional `DeprecationWarning` on first import of `src` (env-gated so
     tests stay quiet until the window starts).
3. Update **first-party** entrypoints only when shim is green:
   - helm chart `command` / uvicorn module path
   - staging Dockerfile CMD
   - `scripts/k8s_staging_up.sh` inline Dockerfile
   - compose if any
4. Gate: unit + contract + a wheel install smoke
   (`python -c "import agentflow_runtime; import src"`).

### Phase 2 — first-party cutover

1. Change in-repo imports `src.` → `agentflow_runtime.` (codemod + review).
2. Keep shim for external consumers / old docs.
3. mypy/ruff package paths, pytest `pythonpath`, coverage sources.

### Phase 3 — remove shim (breaking release)

1. Drop top-level `src` from the wheel.
2. Changelog + migration note in `docs/migration/`.
3. Tag as minor/major per semver policy for the release line.

## Compatibility matrix (related P2-6 tail)

| Artifact | Versioning today | Note |
|----------|------------------|------|
| `agentflow-runtime` | `2.0.0` in pyproject | This plan |
| Python SDK `sdk/` | separate | Pin matrix in contract tests later |
| TS SDK `sdk-ts/` | separate | Same |
| `integrations/` | `1.0.1`, not in main publish workflow | Declare internal **or** promote |

Do not block the namespace rename on integrations publish.

## Verification checklist (when implementing)

- [ ] `python -m build` wheel contains `agentflow_runtime/…` and (phase 1–2) `src/…` shim only
- [ ] `pip install dist/*.whl` → both import styles work in phase 1–2
- [ ] helm/staging still boots API (`uvicorn …:app`)
- [ ] bridge: `python -m agentflow_runtime.processing.bridge_consumer` (or shim module path)
- [ ] CI unit + contract green; no accidental `packages = ["src"]` only

## Decisions (defaults for the release window)

Recorded 2026-07-17 so implementation is not blocked on recap — still **do not
code Phase 1** until the release branch is opened.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Layout | **`src/agentflow_runtime/`** (src-layout) | Keeps `src/` as the container dir; hatch packages `agentflow_runtime`; matches modern packaging without dumping the whole monorepo root. |
| Shim lifetime | **One minor line** (e.g. 2.1 ships dual import; 2.2 drops `src` top-level) | Enough for first-party cutover + external consumers; not forever. |
| DeprecationWarning on `import src` | **Off until Phase 2 complete**, then on by default (env `AGENTFLOW_SRC_SHIM_SILENT=1` to mute) | Avoids CI noise during mass codemod. |

## Phase 0 inventory — done 2026-07-17 (`main` @ `4a5d524`)

### Wheel today

```text
python -m build --wheel
→ agentflow_runtime-2.0.0-py3-none-any.whl  (~342 KB, 145 files)
top-level package dir in wheel:  src/   (141 files under src/)
```

Distribution name is already `agentflow-runtime`; only the **import package**
is the generic `src`.

### Hatch

```toml
[tool.hatch.build.targets.wheel]
packages = ["src"]
```

CI mypy: `mypy src/ --ignore-missing-imports` (`.github/workflows/ci.yml`).

### Runtime entrypoints hardcoding `src.`

| Kind | Hits (repo scan, excl. .venv/.git) | Examples |
|------|-----------------------------------:|----------|
| `python -m src.…` | 47 | bridge_consumer, local_pipeline, provision docs |
| `uvicorn src.…` | 12 | `Dockerfile.api`, `docker-compose.prod.yml`, `k8s_staging_up.sh`, load/perf workflows |
| `src.serving.api.main` | 100 | helm deployment + worker, benchmarks, chaos/e2e |
| `src.serving.provision` | 27 | helm provision Job, tests, main lifespan notes |
| `src.processing.bridge_consumer` | 11 | bridge tests, main |
| `packages = ["src"]` | 6 | pyproject (+ mutants / plan / audit) |
| `from src.` / `import src.` lines in `src/`+`tests/`+`scripts/` | **~540** | primary codemod surface |

### Helm / image (must change in Phase 1–2 with shim)

- `helm/agentflow/templates/deployment.yaml` → `uvicorn` `src.serving.api.main:app`
- `helm/agentflow/templates/deployment-worker.yaml` → same
- `helm/agentflow/templates/provision-job.yaml` → `src.serving.provision`
- `Dockerfile.api` CMD → `src.serving.api.main:app`
- `scripts/k8s_staging_up.sh` patch args → same

### Blast radius (honest)

- **~540** first-party import lines + **~100** `main:app` string references +
  helm/docker/compose.
- Shim Phase 1 is mandatory; big-bang rename without shim will break every
  image and local `python -m` habit the same day.

### Phase 0 exit criteria

- [x] Entrypoint inventory
- [x] Hatch pin confirmed
- [x] Baseline wheel tree recorded (`src/` top-level only)
- [x] Default decisions written (layout / shim / warnings)
- [ ] Phase 1 on a release branch (not started)
