# T01 — Repo hygiene sweep

**Priority:** P0 · **Estimate:** 30 мин

## Goal

Убрать из git tree артефакты, раздувающие clone, синхронизировать `.gitignore`.

## Context

- Репо: `D:\DE_project\` (AgentFlow, real-time data platform, Python FastAPI + Kafka/Flink/Iceberg/DuckDB)
- Состояние: v1.0.1 на `main`, clean, 543 теста зелёных
- В корне обнаружены артефакты:
  - `.tmp/verify-clone/` (~500MB копия репо от публикационного процесса v18)
  - `infrastructure/terraform;W/` (пустая директория, опечатка в имени)
  - `D:DE_projectdocsplans/` (директория с литеральным Windows-путём как именем, artifact от бага в команде)
  - `agentflow_api.duckdb` (41MB бинарь runtime state)

## Deliverables

1. Удалить из git tree:
   ```bash
   git rm -r --cached .tmp/verify-clone
   git rm -r --cached 'infrastructure/terraform;W'
   git rm -r --cached 'D:DE_projectdocsplans'
   git rm --cached agentflow_api.duckdb
   ```
2. Удалить физически:
   ```bash
   rm -rf .tmp/verify-clone 'infrastructure/terraform;W' 'D:DE_projectdocsplans' agentflow_api.duckdb
   ```
3. `.gitignore` — добавить блок:
   ```
   # runtime artifacts
   .tmp/
   *.duckdb
   *.duckdb.wal
   ```
4. Один коммит `chore: remove publication artifacts and runtime binaries from tree`

## Acceptance

- `git ls-files | grep -E "^(\.tmp|agentflow_api\.duckdb|D:DE_project|infrastructure/terraform;W)"` возвращает пусто
- `make test` зелёный (local demo может пересоздавать `agentflow_api.duckdb` на лету — убедиться что это работает и файл корректно игнорируется)
- `git status` чистый после коммита
- `du -sh .git` не вырос

## Notes

- НЕ удалять `.tmp/` целиком из working tree — только `.tmp/verify-clone/`. Возможно там есть активные файлы
- Если `agentflow_api.duckdb` нужен для local demo — добавить `Makefile` target `make demo-db` который его создаёт из `scripts/` (не обязательно для этого таска, можно отдельным PR)
- Имя `infrastructure/terraform;W` содержит `;` — экранировать в shell и git команде
