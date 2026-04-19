# Phase 4 closure — оркестратор

Цель: довести Phase 4 до clean working tree с осмысленной git-историей.
Состояние сейчас — 216 файлов в staging (24 M + 192 untracked), содержит
мусор + большую реальную работу.

## Порядок (СТРОГО последовательно, в одной Codex-сессии)

### 1. task-P4A — Hygiene (~5 мин)
Файл: `codex-tasks/task-P4A-hygiene.md`

Расширить `.gitignore`, удалить сессионные .md и .duckdb.wal, 1 commit.

**Критерий перехода к P4B:** `git status --short | wc -l` уменьшился
до ~130-150, `.gitignore` закоммичен.

### 2. task-P4B — Commit series (~20-30 мин)
Файл: `codex-tasks/task-P4B-commit-series.md`

8 логических коммитов по слоям: CI/deploy → API core → routers →
serving → modified → SDKs → tests → docs.

**Критерий перехода к P4C:** `git status` clean, baseline 79 тестов
проходит.

### 3. task-P4C — Verify (~10 мин)
Файл: `codex-tasks/task-P4C-verify.md`

Полная проверка: imports, tests, lint, docker, endpoints. **Никаких
коммитов** — только отчёт.

## Post-closure — архив спеков

```bash
git mv codex-tasks/task-P4A-hygiene.md codex-tasks/Archive/
git mv codex-tasks/task-P4B-commit-series.md codex-tasks/Archive/
git mv codex-tasks/task-P4C-verify.md codex-tasks/Archive/
git mv codex-tasks/phase-4-closure.md codex-tasks/Archive/
git commit -m "Archive Phase 4 closure specs"
```

## Hard rules (для всех трёх тасков)
- **Никаких `git add .` / `git add -A`** кроме прямо указанных мест в P4B
- **Никаких `--no-verify`, `push --force`, `reset --hard`**
- Между commit'ами ревьюить `git status --short | head -20`
- При любых import errors в sanity check — СТОП, диагностика, не ехать
  дальше
- Если `pytest` baseline (79 тестов) ломается — откатить последний
  commit, разобраться

## DONE WHEN
- [ ] P4A: 1 commit (.gitignore)
- [ ] P4B: 8 commits (CI/deploy → ... → docs)
- [ ] P4C: отчёт (без коммитов)
- [ ] Archive: 1 commit (4 файла)
- [ ] `git log --oneline -14` читается
- [ ] `git status` clean
- [ ] Baseline 79 tests passing
- [ ] Отчёт P4C приложен к финальному сообщению

## Общее количество: 10 коммитов + отчёт
