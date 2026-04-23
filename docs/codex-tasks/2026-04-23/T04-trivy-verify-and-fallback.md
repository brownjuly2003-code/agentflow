# T04 — Trivy: verify ignore-unfixed, add `.trivyignore` fallback

**Priority:** P1 · **Estimate:** 1-2ч

## Goal

В `.github/workflows/security.yml` job `trivy` ранее падал на HIGH/CRITICAL CVE в production image. Применён `ignore-unfixed: true` (CVE без upstream patch не блокируют CI). Нужно (a) убедиться что после этого CI зелёный, (b) если остались actionable findings — обновить базовый образ/dep-ы или, если фикс невозможен timely, добавить `.trivyignore` с конкретными CVE и обоснованием.

## Context

- Workflow: `.github/workflows/security.yml`, job `trivy`. Сканит образ `agentflow-api:security-scan` (build из `docker-compose.prod.yml`). Severity `HIGH,CRITICAL`, `ignore-unfixed: true` (после моего change).
- Базовый образ `python:3.11-slim` (Debian 13.4 в скане прошлого run-а).
- Прошлый failed run: 87 OS пакетов проверено + Python deps. Точный список CVE в SARIF (не сохранился в логе run 24809054268 потому что Trivy печатает их в stdout, который не показывается на failure).
- Контракт: `trivy-results.sarif` всегда апается в Security tab GitHub (`if: always()`), даже если шаг fail. Можно посмотреть детали в UI repo Security → Code scanning.

## Deliverables

1. После того как T01/T02/T03 запушены и Trivy job отработал хотя бы раз с `ignore-unfixed: true`:
   - Если зелёный — задокументировать в `docs/codex-tasks/2026-04-23/T04-result.md` "Trivy clean after ignore-unfixed" и закрыть таск.
   - Если красный — продолжить пунктами 2-5.
2. Скачать SARIF из последнего failed run-а (`gh run download <run-id> -n trivy-results.sarif`) или из Security tab; извлечь список actionable CVE (severity HIGH|CRITICAL, fix_version != null).
3. Для каждой CVE — решение:
   - **Fixable update** (минорный bump dependency или base image): обновить `pyproject.toml` (например, `requests>=2.32` если CVE в requests<2.32) или `Dockerfile` (`FROM python:3.11.10-slim` → newer patch). Один dep upgrade = один коммит, чтобы при regression легко откатить.
   - **No reasonable fix** (transitive dep, nothing to upgrade, или waiting on upstream): добавить в `.trivyignore` с форматом:
     ```
     # CVE-2024-XXXXX: <package> <version> — fix-version <X> requires major bump of <Y>, scheduled for v1.2 sprint
     CVE-2024-XXXXX
     ```
   - НЕ игнорировать без записанного обоснования.
4. После каждого fix/ignore — push и убедиться в зелёном Trivy job-е.
5. Один коммит на upgrade пакета: `chore(deps): bump <package> to <version> for CVE-2024-XXXXX (HIGH)`. Один коммит на `.trivyignore`: `chore(security): trivyignore CVE-2024-YYYYY pending upstream fix`.

## Acceptance

- `Security Scan` workflow зелёный на push в main, jobs `bandit`, `safety`, `trivy` все три зелёные.
- Если использован `.trivyignore` — каждая запись имеет комментарий с обоснованием (`# CVE-XXXX: reason, target fix date`).
- В Security tab GitHub нет HIGH/CRITICAL alerts с available fix.
- Build образа всё ещё работает (`docker compose -f docker-compose.prod.yml build agentflow-api`).

## Notes

- НЕ переключать severity на `MEDIUM,HIGH,CRITICAL` или `--exit-code 0` — теряем actionable signal.
- НЕ ставить `ignore-unfixed: false` обратно — без него CI падал на CVE которые мы физически не можем починить (upstream не выпустил patch).
- Если базовый образ требует major bump (3.11→3.12) — это отдельный таск (test all 552 tests, check Flink compat). Здесь — только safe minor/patch updates.
- `safety<3` уже используется в job `safety`. Если он находит ту же CVE что и Trivy — там тоже надо обновить (fail-safe).
- `bandit` (статический анализ) и `safety` (dep CVE) уже зелёные согласно прошлому run-у — не трогать.
