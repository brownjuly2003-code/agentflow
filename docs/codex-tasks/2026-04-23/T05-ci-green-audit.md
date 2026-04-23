# T05 — CI green audit: каждый workflow на main зелёный

**Priority:** P2 · **Estimate:** 2-4ч

## Goal

После merge T01-T04 — пройтись по всем 15 workflow-ам в `.github/workflows/`, для каждого подтвердить зелёный статус хотя бы на одном recent run (push в main или manually triggered). Workflows которые остаются красными — для каждого один из:

- быстрый fix (если <30 мин эффорта)
- ТЗ для Codex в `docs/codex-tasks/2026-04-24/` (для следующей итерации)
- временный disable (только если workflow явно сломан и есть план починки)

## Context

Workflows в репо (по `ls .github/workflows/`):

| Workflow                | File                       | Triggers                       | Прошлый статус (2026-04-23) |
| ----------------------- | -------------------------- | ------------------------------ | --------------------------- |
| CI                      | `ci.yml`                   | push/PR main                   | red (ruff/mypy)             |
| Contract Tests          | `contract.yml`             | push/PR main                   | red                         |
| Load Test               | `load-test.yml`            | push/PR main                   | red                         |
| Security Scan           | `security.yml`             | push/PR main, weekly cron      | red (Trivy)                 |
| Staging Deploy          | `staging-deploy.yml`       | push main                      | red (helm timeout)          |
| E2E Tests               | `e2e.yml`                  | push main                      | red (compose timeout)       |
| Backup                  | `backup.yml`               | scheduled                      | unknown                     |
| Chaos                   | `chaos.yml`                | scheduled (T04 фикс)           | unknown                     |
| DORA                    | `dora.yml`                 | scheduled                      | unknown                     |
| Mutation                | `mutation.yml`             | scheduled / manual             | unknown                     |
| Performance             | `performance.yml`          | scheduled / manual             | unknown                     |
| Perf Regression         | `perf-regression.yml`      | PR main                        | unknown                     |
| Publish NPM             | `publish-npm.yml`          | tag                            | unknown (last v1.0.1)       |
| Publish PyPI            | `publish-pypi.yml`         | tag                            | unknown (last v1.0.1)       |
| Terraform Apply         | `terraform-apply.yml`      | manual / on terraform/ change  | unknown                     |

После T01 (test-unit), T02 (staging), T03 (e2e), T04 (trivy) — должны быть зелёные: CI, Staging Deploy, E2E Tests, Security Scan. Остальные нужно проверить.

## Deliverables

1. Для каждого workflow в таблице:
   - Запустить (`gh workflow run <name>`) или подождать естественный trigger.
   - Получить статус (`gh run list --workflow <name> --limit 1`).
   - Если зелёный — отметить в чеклисте, продолжить.
   - Если красный — открыть log (`gh run view <id> --log-failed`), классифицировать:
     - `quick fix` — <30 мин: починить в этом же PR
     - `needs ticket` — больше: написать ТЗ в `docs/codex-tasks/2026-04-24/T<NN>-<name>.md` следуя формату README.md из этого спринта
     - `disable` — если workflow сломан принципиально и не нужен сейчас (например, terraform-apply без AWS creds): добавить `if: false` в `jobs.<job>.if` с комментарием `# disabled 2026-04-23: see codex-tasks/2026-04-24/TXX`, открыть ticket для re-enable.
2. Создать файл `docs/codex-tasks/2026-04-23/T05-result.md` со сводкой:
   ```markdown
   # T05 result — CI green audit (2026-04-23)
   
   | Workflow | Status | Action | Run/Ticket |
   |----------|--------|--------|------------|
   | CI | green | — | <run-id> |
   | Contract Tests | red | quick fix in this PR | <commit-sha> |
   | Load Test | red | needs ticket | T11-load-test-throughput.md |
   | ... |
   ```
3. Все quick fix-ы — в этом же PR, отдельные коммиты с понятными message-ами.
4. Memory update: после merge — обновить `~/.claude/projects/D--/memory/project_de_project.md` секцию "State" с новой реальностью CI и оставшимся `НЕ сделано` списком (только то, что осталось красным).

## Acceptance

- Все 15 workflows: либо зелёный recent run на main, либо есть ticket в `2026-04-24/` либо явный `if: false` с обоснованием.
- `T05-result.md` существует и заполнен.
- При просмотре `https://github.com/<owner>/agentflow/actions` страница `main` branch — нет красных runs за последние 24 часа (за исключением intentionally disabled workflows).

## Notes

- НЕ исправлять complex workflows тут (например, Mutation testing, который занимает >1 часа) — они должны идти отдельным PR после изоляции и понимания.
- Cron-only workflows (DORA, Backup) — можно `gh workflow run` для проверки руками.
- Publish workflows (NPM, PyPI) — НЕ запускать через `workflow_dispatch` без необходимости release; вместо этого посмотреть последний tag run (`v1.0.1`).
- Terraform-apply — если требует AWS creds которых нет в OIDC (T03 предыдущего спринта частично закрыл) — это «disable + ticket» case, не quick fix.
- Если в процессе нашлись workflows которые дублируют друг друга (например, два CI definition-а) — отметить, но НЕ удалять без отдельного решения с юзером.
- Backstop: если за 4 часа не получается все 15 — приоритезировать по влиянию (push-triggered первые: CI, Contract, Security, E2E, Staging, Load), отчитаться по ним, остальное — в `2026-04-24/`.
