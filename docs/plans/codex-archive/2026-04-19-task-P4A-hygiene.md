# Task P4A — Hygiene pass перед коммитами

## Context
Рабочее дерево: **24 M + 192 untracked**. Среди untracked — мусор
(runtime artifacts, сессионные отчёты, логи), который НЕЛЬЗЯ коммитить.
До любых commit'ов надо:
1. Расширить `.gitignore`
2. Удалить с диска временные .md отчёты
3. Подтвердить что `mutants/`, `node_modules/`, `.artifacts/` etc. не
   попадут в staging

## Preconditions
- Last commit: `d7675fe docs: update all documentation and add workflow state`
- `git status --short | wc -l` → ~216

## 1. Расширить `.gitignore`

Добавить в конец существующего `.gitignore`:

```
# Runtime artifacts
.artifacts/
.hypothesis/
.iceberg/
.tmp/
.dora/
.bandit-baseline.json

# DuckDB runtime state
*.duckdb.wal
*.duckdb.tmp/

# Node
node_modules/

# Mutation testing output
mutants/

# Devcontainer cache (if project doesn't need it checked in — verify)
# .devcontainer/

# Session artifact files (all временные .md отчёты)
codex_res.md
res_co.md
rep.md
more_help.md
BCG_audit.md
About_DE_project.md
RELEASING.md
"AgentFlow*
agentflow_bench_debug*.duckdb*
agentflow_demo_api.duckdb*
```

**Проверка после правки:**
```bash
git check-ignore -v mutants/ .artifacts/ agentflow_bench_debug.duckdb.wal \
  codex_res.md rep.md node_modules/ 2>&1
# Каждый должен показать .gitignore:<line>:<pattern>	<file>
```

## 2. Удалить с диска сессионные артефакты

**Важно:** эти файлы НЕ в git'е, просто на диске. Удаляем физически:

```bash
rm -f codex_res.md res_co.md rep.md more_help.md BCG_audit.md \
      About_DE_project.md RELEASING.md
rm -f "AgentFlow"*
rm -f agentflow_bench_debug*.duckdb.wal agentflow_demo_api.duckdb.wal
```

**НЕ трогать:**
- `docs/benchmark*.md` — это документация, не сессии
- `.devcontainer/` — проверить содержимое отдельно (может быть нужен)

## 3. Проверить что `.devcontainer/` — реальный или мусор

```bash
ls .devcontainer/ 2>&1
cat .devcontainer/devcontainer.json 2>&1 | head -20
```
Если это валидная VSCode dev container config — оставить unstaged, пусть
будет untracked до отдельного решения. Если мусор — удалить.

## 4. Commit: только .gitignore

```bash
git add .gitignore
git commit -m "Expand .gitignore: runtime artifacts, mutation testing, session notes (task-P4A)"
```

После этого коммита `git status --short` должен показать резкое
сокращение untracked — все бинарники, артефакты, и сессионные .md
перестают светиться.

## CONSTRAINTS
- **НЕ** использовать `git add .` / `git add -A` пока `.gitignore` не
  закоммичен — иначе мусор попадёт в staging
- НЕ удалять ничего из `src/`, `tests/`, `docs/`, `deploy/`, `config/`,
  `.github/`, `infrastructure/`, `k8s/`, `sdk/`, `sdk-ts/`, `monitoring/`,
  `warehouse/`, `notebooks/` — это реальная работа
- Файлы `*.md` удалять ТОЛЬКО из списка выше; не трогать `docs/*.md`,
  `README.md`, `CHANGELOG.md`

## DONE WHEN
- [ ] `.gitignore` расширен патернами выше
- [ ] Сессионные .md + .duckdb.wal удалены с диска
- [ ] `git check-ignore` подтверждает что `mutants/`, `.artifacts/`,
      `*.duckdb.wal` игнорируются
- [ ] `git status --short | wc -l` заметно меньше 216 (ожидание: ~130-150)
- [ ] 1 коммит: "Expand .gitignore: runtime artifacts, mutation testing, session notes (task-P4A)"

## STOP conditions
- Если после правки .gitignore какой-то tracked файл начнёт игнорироваться
  (показывается в `git ls-files -i -c --exclude-standard`) — откати правку
  gitignore, уточни паттерн
- Если `.devcontainer/` содержит что-то нестандартное — СТОП, спроси
