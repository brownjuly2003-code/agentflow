# T04 — Chaos full suite on schedule

**Priority:** P1 · **Estimate:** 2-3ч

## Goal

`.github/workflows/chaos.yml` сейчас запускает только smoke на PR. Добавить scheduled full-suite run + создание GitHub issue при падении.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Full chaos suite живёт в `tests/chaos/` — сценарии: Kafka down, Redis down, Flink restart, disk pressure, network partition
- На PR path — только smoke (1-2 сценария) для скорости, это правильно
- Полный suite должен бежать по расписанию, чтобы ловить slow regression
- Workflow уже существует — `.github/workflows/chaos.yml`, нужно расширить

## Deliverables

1. **Обновить** `.github/workflows/chaos.yml`:
   - Добавить trigger:
     ```yaml
     on:
       pull_request:
         paths: [...]  # сохранить существующий
       schedule:
         - cron: '0 4 * * *'  # ежедневно 04:00 UTC
       workflow_dispatch:
     ```
   - Новый job `chaos-full`:
     - `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'` — не бежит на PR
     - Запускает `pytest tests/chaos/ -m "not smoke"` (или эквивалент — прочитать `pyproject.toml`/`pytest.ini`/`conftest.py` чтобы понять какие markers используются)
     - Timeout: 30 минут
   - Существующий job `chaos-smoke` — ограничить `if: github.event_name == 'pull_request'`

2. **Notification on failure** — в конце job `chaos-full`:
   ```yaml
   - name: Create issue on failure
     if: failure()
     uses: actions/github-script@v7
     with:
       script: |
         github.rest.issues.create({
           owner: context.repo.owner,
           repo: context.repo.repo,
           title: `Chaos scheduled run failed — ${new Date().toISOString().split('T')[0]}`,
           body: `Workflow run: ${context.payload.workflow_run?.html_url || `https://github.com/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`}\n\nReview logs and investigate which scenario regressed.`,
           labels: ['chaos-failure', 'severity:high']
         })
   ```

3. **Документация** — дополнить `docs/operations/chaos-runbook.md` (или создать если нет) секцией:
   - «When a scheduled chaos issue opens»: шаги triage, где смотреть логи, как повторить locally (`make chaos-local` или `docker compose -f docker-compose.chaos.yml up`)
   - Severity escalation matrix

## Acceptance

- `gh workflow view chaos.yml` показывает `schedule` и `workflow_dispatch` triggers
- `workflow_dispatch` запуск (через `gh workflow run chaos.yml`) проходит full suite без падений на healthy окружении
- PR на тривиальное изменение НЕ триггерит `chaos-full` job (проверить через dry-run PR)
- Имитация failure (намеренно сломать один scenario локально, пушнуть на feature branch, запустить `workflow_dispatch`) → issue создаётся с правильными labels
- `docs/operations/chaos-runbook.md` дополнен

## Notes

- НЕ блокировать merge на scheduled runs (это observability, не gate)
- Если Slack notification есть в других workflows (например `security.yml`) — переиспользовать тот же action/webhook для consistency, не заводить новую интеграцию
- Scheduled cron в UTC, 04:00 — низкая нагрузка. Если проект имеет peak hours — подобрать под них
- Commit message: `ci(chaos): add scheduled full-suite run with failure notifications`
