# TA05 — Stale code + dead artifacts scan

**Priority:** P2 · **Estimate:** 1-2ч

## Goal

Найти dead code, orphan тесты, и runtime artifacts которые попали в git tree (вроде `agentflow_api.duckdb` в прошлом T01 спринта).

## Context

- Прошлый репо-hygiene fix — коммит `dfc6753` (T01 v1.1 sprint) убрал `.tmp/verify-clone/`, `D:DE_projectdocsplans/`, `agentflow_api.duckdb`. Может появиться новое.
- Dead code часто появляется после refactor-ов (T00 hardening мог оставить unreferenced helpers).
- Тесты которые тестировали удалённые модули — становятся orphan.

## Deliverables

1. **Unused Python modules** (статический анализ):
   ```bash
   pip install vulture
   vulture src/ tests/ --min-confidence 80 > audit-vulture.txt
   ```
   Отфильтровать false positives (FastAPI route handlers, pytest fixtures, ABC implementations) — оставить актуальные.
2. **Unused imports / variables**:
   ```bash
   ruff check src/ tests/ --select F401,F841 --output-format concise
   ```
   (F401 unused import, F841 unused variable). T00 уже почистил очевидные — должно быть пусто.
3. **Orphan test files** (тесты для несуществующих модулей):
   ```bash
   for testfile in tests/**/*.py; do
     # Найти `from src.X import` patterns, проверить что src/X.py existence
     ...
   done
   ```
4. **Runtime artifacts в git tree**:
   ```bash
   git ls-files | grep -E "\.(duckdb|wal|cache|tmp|log|pid)$"
   git ls-files -X .gitignore  # if any tracked file matches gitignore — broken
   ```
5. **Dead branches / stale tags**:
   ```bash
   git branch -a | grep -v "main\|HEAD"
   git tag --list | head -20  # последние tags, проверить что v1.0.1 есть
   ```
6. **Untracked files в working dir** (что ещё не в git):
   ```bash
   git status --short --ignored | head -30
   ```
7. **Stale docs**:
   ```bash
   ls docs/plans/  # plans старше 30 дней — кандидаты на archive
   ls docs/codex-tasks/  # closed sprints (2026-04-22) — оставить или archive?
   ```

Финальный `audit/TA05-result.md`:

```markdown
## Stale code + artifacts scan

### Unused modules (vulture, confidence ≥80)
| File | Symbol | Recommendation |

### Unused imports (ruff F401/F841)
| File:Line | Symbol | Recommendation |

### Orphan test files
| Test | Imports missing src/ module | Action |

### Runtime artifacts in tree
| File | Size | Action (delete/gitignore) |

### Stale docs
| Path | Last modified | Recommendation (archive/delete/keep) |

### Untracked / .gitignored
| Path | Note |
```

Action — никогда не «delete» сразу; всегда `recommend delete` или `recommend archive` с обоснованием. **Reality check** в TA10 consolidation решит что делать.

## Acceptance

- `audit/TA05-result.md` содержит все 5 секций.
- НИЧЕГО не удалено в этом таске. Только recommendations.
- Если найдены runtime artifacts — обновить `.gitignore` отдельным коммитом `chore(gitignore): block <pattern>` и `git rm --cached` файла. Это единственный allowed mutation.

## Notes

- Vulture даёт много false positives на FastAPI/pytest — фильтровать вручную, не доверять blind.
- НЕ удалять docs которые содержат «planning» / «plan» / «roadmap» — даже old, могут содержать context для будущих решений.
- НЕ archive `docs/codex-tasks/2026-04-22/` — sprint всего месяц назад, recent context.
- Backstop: если vulture + ruff занимают весь час — оставить sections 3-7 как `partial — see follow-up TXX in 2026-04-24/`.
