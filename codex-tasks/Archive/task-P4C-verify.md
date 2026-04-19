# Task P4C — Финальная верификация Phase 4

## Context
P4A (hygiene) + P4B (8 commit'ов) завершены. Надо убедиться, что
репозиторий в здоровом состоянии до передачи на staging.

## Preconditions
- `git status` → clean
- Последние 9 коммитов: P4A + 8 из P4B

## 1. Структурная целостность

```bash
# Все Python-модули импортируются
python -c "
import importlib, pkgutil, sys
sys.path.insert(0, 'src')
failed = []
for mod in pkgutil.walk_packages(['src'], prefix=''):
    try:
        importlib.import_module(mod.name)
    except Exception as e:
        failed.append((mod.name, str(e)[:200]))
for m, e in failed:
    print(f'FAIL {m}: {e}')
print(f'Failed: {len(failed)}')
"
```

Ожидание: 0 failed (или только модули, которым нужны runtime deps типа
pyflink, kafka-python — перечислить в отчёте).

## 2. Полный прогон тестов

```bash
pytest tests/unit/ -q --ignore=tests/unit/test_llamaindex_reader.py \
                      --ignore=tests/unit/test_crewai_tools.py \
                      --ignore=tests/unit/test_langchain_tool.py \
                      2>&1 | tail -10
# Исключаем тесты, требующие тяжёлых опциональных deps (LangChain,
# LlamaIndex, CrewAI) — их прогон отдельно.

pytest tests/integration/ -q --ignore=tests/integration/test_kafka_pipeline.py \
                             --ignore=tests/integration/test_flink_session.py \
                             --ignore=tests/integration/test_iceberg_sink.py \
                             2>&1 | tail -10
# Исключаем тесты, требующие поднятых Kafka/Flink/Iceberg.
```

Фиксировать числа: unit passed, integration passed. Любые failures —
отчёт какие, stack trace первой ошибки.

## 3. Lint / static

```bash
ruff check . 2>&1 | tail -5
```
Если > 0 errors — список категорий (`ruff check . --statistics`), но
**не фиксить** в этой задаче; отдельный task-P4D если надо.

```bash
python -m mypy src/ 2>&1 | tail -10 || echo "mypy not configured or fails"
```
(Если mypy есть — количество errors; не фиксить.)

## 4. Сетевая валидация (приложение стартует)

```bash
timeout 15 python -m uvicorn src.serving.api.main:app --port 18181 &
sleep 5
curl -s http://localhost:18181/v1/health 2>&1 | head -5
kill %1 2>/dev/null
```
Ожидание: `{"status": "healthy", ...}` или аналогичный JSON 200.

## 5. Docker build smoke

```bash
docker build -f Dockerfile.api -t agentflow:test . 2>&1 | tail -15
```
Если падает — зафиксировать на каком шаге; не фиксить в этой задаче.

## 6. Deploy config sanity

```bash
# fly.toml валиден
python -c "import tomllib; tomllib.load(open('deploy/fly/fly.toml', 'rb'))"

# Проверка что /v1/health всюду согласован
grep -r "/v1/health" deploy/ .github/workflows/ 2>&1 | head -10
grep -r "/health" deploy/ --include="*.toml" --include="*.yml" 2>&1 | head -5
# Не должно быть путей /health без /v1 префикса в deploy configs
```

## 7. API surface count

```bash
python -c "
import sys
sys.path.insert(0, 'src')
from serving.api.main import app
v1_paths = sorted({r.path for r in app.routes if r.path.startswith('/v1')})
print(f'Unique /v1 paths: {len(v1_paths)}')
for p in v1_paths: print(p)
" | head -50
```
Сравнить с `docs/api-reference.md` — все ли 41+ пути задокументированы.

## DONE WHEN
- [ ] Все Python модули в `src/` импортируются без ошибок
- [ ] unit tests: N passed (зафиксировать число)
- [ ] integration tests (без Kafka/Flink): M passed (зафиксировать)
- [ ] ruff errors: K (зафиксировать; фиксить отдельно)
- [ ] `/v1/health` отвечает 200 на запущенном приложении
- [ ] `fly.toml` валиден, `/v1/health` согласован в deploy/
- [ ] Docker build: success / failure (зафиксировать)
- [ ] Отчёт одной страницей: пройдено / что оставить на дозадачу

## Формат отчёта в комментарий commit'а
Не делать никаких коммитов в P4C — это чистая верификация. Отчёт в
summary при передаче пользователю:

```
P4C verification report:
- Imports: X/Y modules OK (если есть failed — перечислить)
- Unit tests: P passed, F failed
- Integration: P passed, F failed, S skipped
- Ruff: K errors, top categories: ...
- Health endpoint: OK / FAIL (reason)
- Docker: builds / fails at step Z
- API docs coverage: docs cover M of N /v1 paths

Recommendation: [ready for staging | нужен P4D fixup task]
```

## STOP conditions
- Критично много import errors (> 5) — скорее всего P4B пропустил
  файлы; СТОП, отчёт какие — чиниться отдельной задачей
- Health endpoint не поднимается — СТОП, отчёт: missing env var? Missing
  dep? Import error в main?
