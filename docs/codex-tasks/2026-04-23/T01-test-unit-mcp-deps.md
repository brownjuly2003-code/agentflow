# T01 — Fix test-unit job: add MCP integration deps

**Priority:** P0 · **Estimate:** 20 мин

## Goal

CI job `test-unit` падает на коллекции тестов из-за `ModuleNotFoundError: No module named 'mcp'`. Установить `mcp` extra пакета `agentflow-integrations` в test-unit job, чтобы тесты собирались.

## Context

- `tests/unit/test_mcp_server.py` (добавлен в T08 предыдущего спринта, коммит `07cb253`) импортирует `agentflow_integrations.mcp.server`, который импортирует `mcp` package.
- Локальная структура: `integrations/pyproject.toml` объявляет `agentflow-integrations` с extras: `mcp = ["mcp>=1.0"]`. Корневой `pyproject.toml` имеет свой `integrations` extra — **другой** (langchain + llama-index-core), без `mcp`.
- CI test-unit (`.github/workflows/ci.yml` строки 50-68) делает `pip install -e ".[dev,integrations]"` — это ставит **корневой** integrations extra, не агентфлоу-интеграционный, поэтому `mcp` пакет отсутствует.
- Локально сейчас: `python -m pytest tests/unit/ tests/property/` падает с тем же `ModuleNotFoundError`. Нужно воспроизвести и зафиксировать.

## Deliverables

1. В `.github/workflows/ci.yml` шаге `Install dependencies` job-а `test-unit` добавить установку `agentflow-integrations[mcp]`:
   ```yaml
   - name: Install dependencies
     run: |
       pip install -e ".[dev,integrations]"
       pip install -e "./integrations[mcp]"
   ```
2. Проверить: остальные jobs (`test-integration`, `test-contract`, и т.д.) — нужен ли им `mcp`? Если в job-е используется `tests/unit/` — да, добавить. Если нет — не трогать.
3. Локально установить `mcp` (`pip install "mcp>=1.0"` или `pip install -e "./integrations[mcp]"`) и убедиться что `python -m pytest tests/unit/ tests/property/` зелёный (552 теста по памяти, может варьироваться ±10).
4. Один коммит `ci(test-unit): install agentflow-integrations[mcp] for MCP server tests`.

## Acceptance

- Локально: `python -m pytest tests/unit/ tests/property/ -q` возвращает `passed` без collection errors.
- CI: после push — job `test-unit` зелёный (или падает на чём-то другом, не на `ModuleNotFoundError: mcp`).
- `pip install -e ".[dev,integrations]" && pip install -e "./integrations[mcp]"` отрабатывает чисто (без resolver conflicts).

## Notes

- Альтернатива: добавить `mcp>=1.0` в корневой `pyproject.toml` `integrations` extra. **НЕ делать так** — это смешивает две разные `integrations` extras и засоряет dep tree корневого пакета. Чище — отдельный `pip install -e "./integrations[mcp]"`.
- Если `mcp` пакет требует Python 3.12+ или other constraint — задокументировать в commit message и применить условный install (`pip install ... || true` нельзя, лучше pin compatible version).
- НЕ трогать сам `test_mcp_server.py` — он корректный, проблема в CI deps.

## Follow-up — pyiceberg в test-unit

После первичного fix-а (commit `8d20684`) `tests/unit/test_mcp_server.py` коллекционируется, но всплыл пре-existing блокер на коллекции `tests/unit/test_chaos_conftest.py` и `tests/unit/test_db_pool.py`:

```
ModuleNotFoundError: pyiceberg
```

`pyiceberg` объявлен в корневом `pyproject.toml` extra `cloud` (строка ~36):

```toml
cloud = [
    "boto3>=1.35,<2",
    "pyiceberg>=0.7,<1",
]
```

Используется через transitive импорты `src/processing/iceberg_sink.py`, `src/processing/local_pipeline.py`, `src/quality/monitors/metrics_collector.py`. Тесты `test_chaos_conftest.py` и `test_db_pool.py` импортируют эти src-модули.

Прецедент починки уже есть: коммит `b2f8344` (`ci(load-test): install cloud extras so the in-job uvicorn can import pyiceberg`) добавил `cloud` в load-test job. Применить тот же паттерн к test-unit:

```yaml
- name: Install dependencies
  run: |
    pip install -e ".[dev,integrations,cloud]"
    pip install -e "./integrations[mcp]"
```

(добавилось `,cloud` к корневому extra; `integrations[mcp]` — без изменений).

Один follow-up коммит: `ci(test-unit): install cloud extras for pyiceberg-using src modules`.

**Acceptance follow-up:**
- `python -m pytest tests/unit/ tests/property/ -q` собирается без `ModuleNotFoundError` (любые import errors отсутствуют) в чистом Python venv после `pip install -e ".[dev,integrations,cloud]" && pip install -e "./integrations[mcp]"`.
- CI test-unit job зелёный или падает уже на test failures (а не на collection errors).

**Не делать в этом таске:**
- НЕ распространять `cloud` extra на test-integration / test-contract / другие jobs. Если они тоже сломаны на pyiceberg — это отдельный fix (в T05 или новом ticket-е), не разрастать T01.
- НЕ менять структуру extras в `pyproject.toml` (например, не выносить pyiceberg в `core`). Юзеру может не нужен cloud для local dev — current разделение корректно.
