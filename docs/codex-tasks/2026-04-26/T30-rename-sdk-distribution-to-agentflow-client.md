# T30 — Rename SDK PyPI distribution `agentflow` → `agentflow-client`

## Goal

Подготовить кодбазу к v1.1.0 release: переименовать **PyPI distribution name** SDK с `agentflow` (имя занято на pypi.org с 2023-05-29 другим разработчиком — `Stoyan Stoyanov / llmflow`, проект abandoned, единственный релиз 0.0.2) на свободное `agentflow-client`. Python module и API не меняются: `from agentflow import AgentFlowClient` продолжает работать (паттерн `Pillow → PIL`).

После закрытия этого таска юзер делает 3 web-UI шага (PyPI Trusted Publishers × 2, NPM token, GH secret), Claude делает re-tag v1.1.0 на новый HEAD, publish workflows запускают релиз.

## Context

- **Repo:** `D:\DE_project\`, branch `main`, working tree должно быть clean. Текущий HEAD: `ab132b3` (2026-04-25, `chore(release): finish 1.1.0 bump in SDK __init__ and version asserts`). Origin: `https://github.com/brownjuly2003-code/agentflow.git`.
- **Версия:** все source-of-truth уже на `1.1.0` (`pyproject.toml`, `sdk/pyproject.toml`, `sdk/agentflow/__init__.py:__version__`, `sdk-ts/package.json`). НЕ менять.
- **Что НЕ трогать:**
  - `sdk/agentflow/` directory — это Python module (import path), остаётся `agentflow`.
  - `from agentflow import ...` во всех файлах — все импорты остаются нетронутыми.
  - `pyproject.toml` (root) — это `agentflow-runtime`, отдельный package.
  - npm scope `@agentflow/client` — отдельная registry; superseded on 2026-04-29 by `@uedomskikh/agentflow-client` because npm org scope `@agentflow` is already owned by another project.
  - GitHub repo name `agentflow` — отдельный namespace.
  - `[tool.agentflow.dependency-profiles]` в `pyproject.toml` — uses path `./sdk`, не distribution name, остаётся.
  - `pip install -e "./sdk"` в `.github/workflows/*.yml` — path-based, остаётся.
  - `pip install agentflow-integrations`, `pip install agentflow-runtime` — другие packages, не трогать.
  - Исторические doc-файлы: `docs/codex-tasks/2026-04-Q2-architecture/A01-...`, `docs/codex-tasks/2026-04-22/T02-...`, `docs/codex-tasks/2026-04-23/T_AUDIT-...`, `docs/codex-tasks/2026-04-23/audit/TA0*-result.md`, `docs/codex-tasks/2026-04-24/T22-v1-1-migration-guide.md`, `docs/codex-tasks/2026-04-24/T21-...`, `docs/plans/codex-archive/*.md`, `CHANGELOG.md` старые секции (`[1.0.x]` и историческая `[1.1.0]` description) — это history record, не active state.
- **A06 enforcement:** `tests/unit/test_contract_dependencies.py` сверяет `pip install` references в docs/README с workflow `pip install` lines. После rename README/migration guide эти assertions должны быть переписаны на `agentflow-client` (см. Deliverable 4). Не трогать workflows напрямую — они уже path-based.
- **Baseline:** `python -m pytest -p no:schemathesis -q` сейчас должен пройти 646 passed, 3 skipped, 0 failed (из memory `project_de_project.md`). После rename ожидается тот же набор.

## Deliverables

Один коммит на main с message:

```
chore(release): rename SDK PyPI distribution agentflow → agentflow-client (T30)

The "agentflow" PyPI name has been occupied since 2023-05-29 by an
unrelated abandoned project (Stoyan/llmflow v0.0.2). PEP 541 takeover
takes 2-6 weeks and is not viable for the current release window.

Rename the SDK PyPI *distribution* to "agentflow-client". Python module
remains `agentflow` so `from agentflow import AgentFlowClient` keeps
working (Pillow→PIL pattern). Pip install command becomes
`pip install agentflow-client`.
```

### 1. `sdk/pyproject.toml`

- `name = "agentflow"` → `name = "agentflow-client"`
- Если есть `[project.urls]` или `description` упоминающие старое имя — adjust if helpful (but minimal touch, не over-edit).

### 2. `sdk/README.md`

- Все `pip install agentflow` → `pip install agentflow-client`
- В шапке коротко добавить: `> Installed from PyPI as **`agentflow-client`**. Python import remains `agentflow`.`

### 3. `sdk/agentflow/__init__.py`

- НЕ трогать. `__version__ = "1.1.0"` уже корректный.

### 4. Тесты

#### `tests/unit/test_version.py`

- `version("agentflow")` → `version("agentflow-client")`. Hardcoded `"1.1.0"` остаётся.

#### `tests/unit/test_sdk_backwards_compat.py`

- `test_version_is_exposed_from_package`: assert `__version__ == "1.1.0"` остаётся (это не distribution name).
- `test_sdk_pyproject_version_matches_release`: assert на pyproject `version` остаётся; ассерта на `name` нет — не нужно добавлять.
- Если в файле где-то есть `version("agentflow")` или явная hardcoded distribution `"agentflow"` (НЕ Python module reference) — заменить на `"agentflow-client"`.

#### `tests/unit/test_contract_dependencies.py`

Файл проверяет что `pip install agentflow` упомянут в `sdk/README.md` и `docs/product.md` (lines 140, 143). После Deliverable 2 и 5 эти assertions должны быть:

- `assert "pip install agentflow-client" in sdk_readme`
- `assert "pip install agentflow-client" in product_doc`

Assertion `"pip install agentflow-integrations" in integrations_doc` (line 145) **не трогать** — `agentflow-integrations` это другой package.

### 5. `docs/product.md`

- Line 41: `pip install agentflow` → `pip install agentflow-client`. Однострочное update — описание SDK install.

### 6. `docs/migration/v1.1.md`

Это T22 migration guide (commit `66f080d`). Все `pip install agentflow` (8+ occurrences) → `pip install agentflow-client`. Добавить отдельный section в начале (после H1, до первого подзаголовка):

```markdown
## ⚠️ PyPI distribution renamed at release time

The SDK PyPI distribution was originally planned as `agentflow` (per A01
Q2 architecture decision), but the name had been occupied on PyPI since
2023 by an unrelated abandoned project. The SDK is published as
**`agentflow-client`** instead. Python imports are unchanged:

| What changed                | Old                     | New                            |
| --------------------------- | ----------------------- | ------------------------------ |
| `pip install` command       | `pip install agentflow` | `pip install agentflow-client` |
| Python import statement     | `from agentflow import` | `from agentflow import` (same) |
| Module name in your code    | `agentflow`             | `agentflow` (same)             |
| `importlib.metadata.version` | `version("agentflow")`  | `version("agentflow-client")`  |
```

Update остальные `pip install agentflow` references в файле на `pip install agentflow-client`. **Не трогать** упоминания `pip install agentflow-runtime` (это root runtime package, не SDK) и `pip install agentflow agentflow-runtime` пример переписать как `pip install agentflow-client agentflow-runtime`.

### 7. `site/index.html`

- Line 214 (install block): `pip install agentflow` → `pip install agentflow-client`. Если рядом есть текст "Install the SDK" — adjust similarly.

### 8. `CHANGELOG.md`

В существующей секции `[1.1.0] - 2026-04-25` добавить bullet (примерный текст, формулируй естественно в стиле остальных bullets):

```
- **SDK PyPI distribution renamed:** Published as `agentflow-client`
  (was planned as `agentflow` in A01, but the name was already taken
  on PyPI by an unrelated abandoned project). Python module and API
  unchanged — `from agentflow import ...` still works. Install with
  `pip install agentflow-client`.
```

Не редактировать историческую секцию `[1.0.x]` или раннее описание `[1.1.0]` если оно уже описывает A01 split.

### 9. `.github/workflows/publish-pypi.yml`

- Line 96 (или соответствующая): comment `# Publish agentflow SDK to PyPI (OIDC)` → `# Publish agentflow-client SDK to PyPI (OIDC)`. Это cosmetic, но согласованно.
- Никаких изменений в `packages-dir`, `with`, `if` — они работают на dist/ files, а не на distribution name.

### 10. Final sweep

`grep -rEn "(\\bagentflow==|pip install agentflow\\b|version\\(\"agentflow\"\\)|name\\s*=\\s*\"agentflow\"\\s*$)" .` — должно вернуть **только**:

- `agentflow-runtime` references (это другой package)
- `agentflow-integrations` references (другой package)
- Исторические doc files в `docs/codex-tasks/`, `docs/plans/codex-archive/`, `docs/codex-tasks/2026-04-Q2-architecture/A01-...` (history, leave intact)
- `CHANGELOG.md` секции до `[1.1.0]` (history)
- Comments в коде typа `# was agentflow before T30`

Любые **active code/docs** references на `agentflow` distribution (НЕ module) должны быть переписаны.

## Acceptance

После rename и до commit:

1. **Lint clean:**
   ```bash
   python -m ruff check src/ tests/
   python -m ruff format --check src/ tests/
   ```
   Both clean.

2. **Install и module check:**
   ```bash
   pip install -e ./sdk
   python -c "import agentflow; print(agentflow.__version__)"        # → 1.1.0
   python -c "from importlib.metadata import version; print(version('agentflow-client'))"   # → 1.1.0
   python -c "from agentflow import AgentFlowClient, AsyncAgentFlowClient; print('imports ok')"
   ```

3. **Тесты:**
   ```bash
   python -m pytest tests/unit/test_version.py tests/unit/test_sdk_backwards_compat.py tests/unit/test_contract_dependencies.py -p no:schemathesis -v
   ```
   All pass.

4. **Full suite:**
   ```bash
   python -m pytest -p no:schemathesis -q
   ```
   `≥ 646 passed, ≤ 3 skipped, 0 failed`. Если число passed выросло — OK; если упало или появились failures — НЕ commit, разбираться.

5. **A06 enforcement:**
   ```bash
   python -m pytest tests/unit/test_contract_dependencies.py -p no:schemathesis -v
   ```
   Все green. (Workflow YAMLs не редактировались — drift не должно возникнуть.)

6. **mypy clean:**
   ```bash
   python -m mypy src/ --ignore-missing-imports
   ```
   No new errors vs baseline.

7. **Commit + push:**
   ```bash
   git add -p   # review каждый change
   git commit -m "$(cat <<'EOF'
   chore(release): rename SDK PyPI distribution agentflow → agentflow-client (T30)

   The "agentflow" PyPI name has been occupied since 2023-05-29 by an
   unrelated abandoned project (Stoyan/llmflow v0.0.2). PEP 541 takeover
   takes 2-6 weeks and is not viable for the current release window.

   Rename the SDK PyPI *distribution* to "agentflow-client". Python module
   remains `agentflow` so `from agentflow import AgentFlowClient` keeps
   working (Pillow→PIL pattern). Pip install command becomes
   `pip install agentflow-client`.
   EOF
   )"
   git push origin main
   ```

8. **CI smoke:** Дождаться CI workflow на push commit. Lint ✓, schema-check ✓, test-unit ✓, test-integration ✓, helm-schema-live ✓, perf-check ✓, terraform-validate ✓, record-deployment ✓. Load Test упасть может (chronic T27b), это не блокер. Если что-то ДРУГОЕ упало — НЕ переходить к release, escalate.

## Notes

- **One commit, atomic.** Не разбивать на серию маленьких коммитов — это release-time fix, должен идти одним diff. Если в процессе работы появится какая-то pre-existing проблема (не related к rename) — оставить её, не fix-and-fold.
- **CX self-check (per `~/.codex/AGENTS.md` rules):**
  - Baseline measurement: 646 passed зафиксировано выше.
  - Shared-file check: каждый файл редактирует только этот таск, нет concurrent CX work.
  - Hardcoded counts grep: после edits run `grep -rE "agentflow.*1\\.1\\.0rc1" .` — должен вернуть только `docs/codex-tasks/2026-04-24/T21-...` (history, OK).
  - Commit gates: один коммит = весь таск, `git push` после CI pre-check локально.
- **Не делать re-tag v1.1.0.** Tag move триггернёт publish workflows, которые упадут потому что Trusted Publishers ещё не настроены. Tag remain на `1ee89a3`. После закрытия этого таска юзер настраивает publishers, после её confirmation Claude делает re-tag.
- **Не публиковать ничего в PyPI/npm.** Это таск только code-changes.
- **Если столкнёшься с тестом который ассертит на `agentflow` distribution, который не был перечислен** — обнови по паттерну (Pillow→PIL), но в commit message добавь bullet `- Updated extra assertion in <file>:<line> (not in original spec).`
- **Если grep на final sweep (Deliverable 10) вернёт что-то непонятное** — лучше overrange the rename (захватить лишнее) и пометить в commit message, чем underrange.
- **Documentation tone:** Migration guide должен быть прямой, без apologies или extensive justification — пользователю нужно знать what to type, не why historical naming had conflicts.
