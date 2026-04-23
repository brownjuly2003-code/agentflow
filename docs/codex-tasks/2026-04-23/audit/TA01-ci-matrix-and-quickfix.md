# TA01 — Quick fix #1 + полная CI workflow matrix

**Priority:** P0 · **Estimate:** 1ч

## Goal

(a) Закрыть очевидную регрессию: `test-integration` job в `.github/workflows/ci.yml` не получил `,cloud` extra в коммите `ecc137c` и валится на `ModuleNotFoundError: pyiceberg`.
(b) Catalog all 15 workflows в `.github/workflows/` с last conclusion на `main`, root cause для красных, action plan.

## Context

- HEAD `b8ba5f7` на `origin/main`
- Workflows в `.github/workflows/`: `backup.yml`, `chaos.yml`, `ci.yml`, `contract.yml`, `dora.yml`, `e2e.yml`, `load-test.yml`, `mutation.yml`, `performance.yml`, `perf-regression.yml`, `publish-npm.yml`, `publish-pypi.yml`, `security.yml`, `staging-deploy.yml`, `terraform-apply.yml`
- На `739ceb4` push сейчас известный статус: ✅ Contract / Security / DORA, ❌ CI / Load Test / Staging Deploy / E2E Tests
- В CI workflow внутри: lint ✅ schema-check ✅ terraform-validate ✅ test-unit ❌ test-integration ❌
- Test-integration `pip install -e ".[dev]"` (~строка 80 в `ci.yml`); прецедент починки — `ecc137c` для test-unit/chaos/perf/perf-regression

## Deliverables

1. **Quick fix:** заменить в `.github/workflows/ci.yml` test-integration step `pip install -e ".[dev]"` на `pip install -e ".[dev,cloud]"`. Один коммит `ci(test-integration): install cloud extras for pyiceberg-using src modules`.
2. **Push** quick fix отдельно от matrix-отчёта — пусть CI прокатится на новом HEAD.
3. **CI matrix** в `audit/TA01-result.md`:
   ```markdown
   ## CI workflow matrix (HEAD <sha after push>)

   | Workflow | Last run | Conclusion | Internal jobs status | Root cause | Action |
   |----------|----------|------------|----------------------|------------|--------|
   ```
   Для каждого workflow:
   - `Last run` = run id + дата последнего run на main
   - `Conclusion` = success / failure / skipped / never_run
   - `Internal jobs status` = `lint:✅ test-unit:❌ ...` (если workflow многоjob-овый)
   - `Root cause` если red — конкретно (не «failed» а «pyiceberg ModuleNotFoundError on collection of test_X.py:Y»)
   - `Action` = один из: `quick fix #N in this PR` / `existing ticket TXX` / `new ticket: TYY-name in 2026-04-24/` / `acceptable until <event>`

## Acceptance

- Quick fix запушен, CI test-integration job на новом HEAD идёт дальше collection (либо зелёный, либо падает на test failure а не collection error).
- `audit/TA01-result.md` существует и содержит matrix всех 15 workflows.
- Каждый ❌ workflow либо имеет fix-action, либо `acceptable until <event>` с обоснованием.
- Новые tickets в `docs/codex-tasks/2026-04-24/` созданы где требуется (с `Goal/Context/Deliverables/Acceptance/Notes`).

## Notes

- НЕ делать больше одного quick fix в этом таске. Любой второй fix — отдельный ticket.
- Manual-trigger workflows (mutation, perf, publish, terraform-apply) — `gh workflow run` для аудита **только если** нет недавнего run-а на main; иначе оставить `Last run` пустым с пометкой `manual-only, never run on main since <date>`.
- На `gh run view` запросы — следить за rate limit (`gh api rate_limit --jq .resources.core`); один `gh run view <id> --json jobs,conclusion,createdAt` на workflow достаточно.
