# AgentFlow — GitHub Publication v18
**Date**: 2026-04-20
**Цель**: commit всех изменений логическими группами + публикация на GitHub
**Executor**: Codex
**Prerequisites**: user уже выполнил `gh auth login`; если нет — **СТОП**, не продолжать

## Prerequisites (проверить ПЕРЕД началом)

```bash
# 1. gh CLI авторизован
gh auth status 2>&1 | grep -q "Logged in to github.com" || { echo "STOP: run 'gh auth login' first"; exit 1; }

# 2. Нет реальных секретов
grep -rnE "sk-[a-zA-Z0-9]{20,}|[A-Z0-9]{20}:[a-zA-Z0-9+/]{40}" \
  --include="*.py" --include="*.ts" --include="*.yaml" --include="*.yml" \
  --include="*.md" --include="*.env*" \
  src/ sdk/ sdk-ts/ config/ docs/ deploy/ 2>&1 | grep -v "example\|EXAMPLE\|test\|REPLACE-ME\|<.*>" | head
# Ожидаемо: пусто (или только placeholders)

# 3. .env в .gitignore
grep -qE "^\.env$|^\.env\s" .gitignore && echo "OK: .env gitignored" || echo "STOP: add .env to .gitignore"

# 4. Нет абсолютных D:/ путей в active docs
grep -rn "D:\\\\\|D:/" README.md docs/*.md 2>&1 | grep -v "docs/plans/" | head
# Ожидаемо: пусто
```

Если любой check падает — **СТОП**, зафиксировать в отчёте, не продолжать до fix.

---

## Граф задач

```
TASK 1  Secrets & hygiene final audit       ← первым
TASK 2  Commit в 4 логических группы         ← после Task 1
TASK 3  Create GitHub repo via gh CLI        ← после Task 2
TASK 4  Push + release + repo settings       ← последним
```

---

## TASK 1 — Final secrets & hygiene audit

### Расширенная проверка

```bash
# Проверить что нет данных:
ls -la agentflow_*.duckdb* 2>&1 | head
# Эти файлы не должны быть в commit. Убедиться что в .gitignore:
grep "agentflow_.*\.duckdb" .gitignore || echo "MISSING gitignore for duckdb"

# Ещё раз secrets scan расширенно
grep -rnE "(password|secret|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{10,}['\"]" \
  --include="*.py" --include="*.ts" --include="*.yaml" --include="*.yml" \
  src/ sdk/ sdk-ts/ config/ 2>&1 | grep -vE "admin-secret.*test|demo-key|<.*>|example|REPLACE" | head -10
# Ожидаемо: пусто (test fixtures с admin-secret/demo-key — OK)

# Абсолютные пути
grep -rn "D:\\\\DE_project\|/D/DE_project\|uedom" README.md CHANGELOG.md LICENSE CONTRIBUTING.md docs/*.md 2>&1 | grep -v "docs/plans/" | head
# Ожидаемо: пусто
```

Если что-то найдено — **fix и retry**, не продолжать.

### Verify

```bash
echo "Hygiene check passed" > .tmp/publication-hygiene-ok.txt
```

---

## TASK 2 — Commit в 4 логических группы

### Group 1: Tests/code/infra changes from Phase 4 cleanup

```bash
# (если что-то осталось в M)
git add .env.example
git commit -m "chore: update .env.example for v1.0.0 release"
```

### Group 2: Research sprint (v16)

```bash
git add docs/plans/2026-04-20-v16-research.md \
        docs/plans/2026-04-20-v16-synthetic-interviews.md \
        docs/v1-1-research.md \
        docs/v1-1-interview-prep.md \
        docs/customer-discovery-questions.md
git commit -m "docs: v1.1 research sprint — MCP/LangChain integration patterns, customer discovery kit

Research-only sprint informing v1.1 feature priorities:
- Framework integration patterns (LangChain, LlamaIndex, MCP)
- Competitive landscape for agent integrations
- Customer discovery script (150+ lines, 5 question blocks)
- Synthetic interviews for script stress-testing
- Top-3 recommendation: MCP read-surface, thin LangChain adapter, freshness primitives"
```

### Group 3: Publication preparation (v17)

```bash
git add README.md LICENSE CONTRIBUTING.md CHANGELOG.md \
        docs/glossary.md docs/publication-checklist.md \
        docs/decisions/0004-v1-publication.md \
        docs/plans/2026-04-20-v17-publication.md
git commit -m "docs: publication prep for v1.0.0 — README, glossary, LICENSE, CHANGELOG

Publication-ready artifacts:
- README.md — public-facing with quick start, architecture, highlights
- LICENSE — MIT
- CHANGELOG.md — v1.0.0 entry with full history v8-v17
- CONTRIBUTING.md — dev setup + PR gates
- docs/glossary.md — 17 key terms explained (testing, p-latencies, circuit breaker, parameterized queries, sqlglot, chaos/load gates, DuckDB+Iceberg, etc.)
- docs/publication-checklist.md — pre-push checklist
- ADR-0004: decision to stop at v1.0.0 without real customer interviews"
```

### Group 4: v18 publication plan itself

```bash
git add docs/plans/2026-04-20-v18-github-publish.md
git commit -m "docs: record v18 GitHub publication plan"
```

### Verify

```bash
git status --short
# Ожидаемо: пусто (clean tree)

git log --oneline -10
# 4 новых commit сверху + предыдущие из v15.5
```

---

## TASK 3 — Create GitHub repo

### Шаги

```bash
# Проверить ещё раз auth
gh auth status

# Создать repo (PUBLIC по умолчанию)
gh repo create agentflow \
  --public \
  --description "Real-time data platform for AI agents. Sub-second entity lookups, typed contracts, dual-language SDK." \
  --source=. \
  --remote=origin

# Note: --source=. linkует current dir как repo source
# Note: --remote=origin добавляет remote автоматически
```

**Если user хочет PRIVATE** — заменить `--public` на `--private`. В плане отразить это явно.

### Verify

```bash
git remote -v
# Ожидаемо: origin → https://github.com/<user>/agentflow.git

gh repo view --json name,visibility,url
# Ожидаемо: visibility=PUBLIC
```

---

## TASK 4 — Push + release + repo settings

### 4.1 Push всей истории

```bash
# Push main branch + история
git push -u origin main

# Проверить что пушнулось
gh repo view --web   # откроет в браузере
```

### 4.2 Create release v1.0.0

```bash
# Release notes из CHANGELOG.md v1.0.0 section
gh release create v1.0.0 \
  --title "AgentFlow v1.0.0 — Initial release" \
  --notes-file <(sed -n '/## \[1.0.0\]/,/^## /p' CHANGELOG.md | head -n -1) \
  --latest
```

### 4.3 Repo settings

```bash
# Topics
gh repo edit --add-topic data-engineering
gh repo edit --add-topic real-time
gh repo edit --add-topic ai-agents
gh repo edit --add-topic fastapi
gh repo edit --add-topic duckdb
gh repo edit --add-topic kafka
gh repo edit --add-topic flink
gh repo edit --add-topic python
gh repo edit --add-topic typescript

# Homepage (опционально — если есть demo URL)
# gh repo edit --homepage https://demo.agentflow.dev

# Enable issues (должно быть on по дефолту)
gh repo edit --enable-issues=true
```

### 4.4 Final verification

```bash
# Свежий clone в temp dir — убедиться что всё чисто
mkdir -p .tmp/verify-clone
cd .tmp/verify-clone
gh repo clone <user>/agentflow
cd agentflow
ls -la README.md LICENSE CHANGELOG.md docs/
# Ожидаемо: все файлы на месте

# Tests проходят на чистом клоне
make setup 2>&1 | tail -3
python -m pytest tests/unit -q 2>&1 | tail -3
cd ../../..
rm -rf .tmp/verify-clone
```

---

## Done When

- [ ] Secrets audit clean (no real secrets leaked)
- [ ] 4 commits созданы с читаемыми сообщениями
- [ ] `git status` clean
- [ ] GitHub repo создан (public, если не указано иное)
- [ ] `git push` успешен, история видна на github.com
- [ ] `gh release create v1.0.0` — release visible
- [ ] Topics проставлены (data-engineering, ai-agents, etc.)
- [ ] Fresh clone в .tmp проверен — всё работает
- [ ] Отчёт с URL репозитория

## Отчёт

```markdown
## v18 GitHub Publication — результат

### Pre-push audit
- Secrets: <clean / found: ...>
- Hygiene checks: <all passed / failures>

### Commits
- Group 1 (env): <hash>
- Group 2 (research): <hash>
- Group 3 (publication): <hash>
- Group 4 (v18 plan): <hash>

### GitHub
- Repo URL: https://github.com/<user>/agentflow
- Visibility: public/private
- Stars: 0 (just created)
- Release: v1.0.0 published

### Fresh clone verification
- make setup: <OK / failed>
- pytest tests/unit: <N passed>

### Next steps for author
1. Open repo in browser, proverit что README рендерится правильно
2. Добавить screenshots (docs/screenshots/) — делается вручную (см. v17 Task 5)
3. Опционально: pin repo в profile
4. Опционально: добавить GitHub Actions badge URL в README после первого CI run
```

---

## Notes

- **НЕ делать force push, amend, rebase** после публикации.
- **НЕ создавать** feature branches и PR'ы — это initial commit на main, дальше пусть автор работает как хочет.
- **Если gh auth падает** — зафиксировать в отчёте, не пытаться обходить. User должен запустить `gh auth login` сам.
- **Не менять** visibility с public на private или наоборот без явного указания в этом плане.
- Если какой-то файл из старой истории содержит что-то чувствительное (даже просто username в путях) — в отчёте указать, но commit всё равно делать (удаление истории = отдельная проблема, за рамки scope).
- **После успеха** — послать URL репо автору в отчёте.
