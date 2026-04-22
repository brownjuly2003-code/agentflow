# AgentFlow — Publication Prep v17
**Date**: 2026-04-20
**Цель**: подготовить проект к публикации на GitHub + создать обучающий glossary для автора проекта
**Executor**: Codex
**Type**: Documentation + publication prep. Никакого изменения логики кода.

## Контекст

v1.0.0 tech-ready, проект идёт в портфолио на GitHub. Нужно:
1. README-уровня публикации (не internal docs)
2. Glossary — пояснение каждого ключевого термина из release highlights (для автора как обучающий материал)
3. Pre-publication hygiene: secrets check, LICENSE, release notes
4. GitHub-ready assets (screenshots, badges)

---

## Граф задач

```
TASK 1  README.md — публикационная версия           ← независим
TASK 2  docs/glossary.md — развёрнутые пояснения    ← независим
TASK 3  Secrets audit + .env.example                ← независим
TASK 4  LICENSE + CONTRIBUTING + release notes      ← независим
TASK 5  Screenshots для README                      ← после Task 1
TASK 6  Final checklist для GitHub publish          ← последним
```

---

## TASK 1 — `README.md` публикационная версия

**Цель:** README, который за 30 секунд отвечает на "что это, почему это интересно, как запустить".

### Структура

```markdown
# AgentFlow

> Real-time data platform for AI agents. Sub-second entity lookups, typed contracts, dual-language SDK.

[![Tests](https://img.shields.io/badge/tests-542_passing-green)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()

## Why this exists

<3-4 предложения: проблема stale data for AI agents → AgentFlow решает через streaming + serving + contracts>

## Highlights

- **543 tests passing** (unit + integration + e2e + property + chaos + contract)
- **p50 entity lookup: 43ms** (down from 26 seconds in initial state — ~600x improvement)
- **Dual SDK** (Python + TypeScript) with retry policies and circuit breakers
- **Security hardened**: parameterized queries, sqlglot AST validator for NL→SQL, bandit baseline gate
- **Full CI/CD**: chaos smoke on PRs, load regression gate (-20% threshold), terraform workflow

## Quick start (5 minutes)

\`\`\`bash
git clone https://github.com/<your-handle>/agentflow
cd agentflow
make setup
source .venv/Scripts/activate  # Windows
make demo
# API на http://localhost:8000
# Docs на http://localhost:8000/docs
# Admin UI на http://localhost:8000/admin (X-Admin-Key: admin-secret)
\`\`\`

### Try it

\`\`\`bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/entity/order/ORD-20260401-1001
\`\`\`

## Architecture

<диаграмма из docs/architecture.md — ASCII или ссылка на SVG>

Stack:
- **Ingestion**: Kafka (KRaft) + Debezium CDC
- **Processing**: Flink (session aggregation, stream processing)
- **Storage**: Iceberg + DuckDB (local)
- **Serving**: FastAPI + custom semantic layer
- **Orchestration**: Dagster
- **IaC**: Terraform + Helm + Docker Compose

See `docs/architecture.md` for ADRs and detailed design.

## What's inside

| Area | Files |
|------|-------|
| API core | `src/serving/api/` |
| Semantic layer (query engine, catalog) | `src/serving/semantic_layer/` |
| Python SDK | `sdk/agentflow/` |
| TypeScript SDK | `sdk-ts/src/` |
| Flink jobs | `src/processing/flink_jobs/` |
| Tests (542) | `tests/` |
| Plans (16 docs, full trail) | `docs/plans/` |
| IaC | `infrastructure/terraform/`, `helm/`, `k8s/` |

## Documentation

- [Architecture](docs/architecture.md) — C4 diagrams, ADRs, tech choices
- [API Reference](docs/api-reference.md) — all endpoints with curl/Python/TS examples
- [Security Audit](docs/security-audit.md) — threat model, controls, compliance posture
- [Competitive Analysis](docs/competitive-analysis.md) — positioning vs Tinybird, Materialize, others
- [Glossary](docs/glossary.md) — key terms and design decisions explained
- [Release Readiness](docs/release-readiness.md) — v1.0.0 evidence pack
- [Audit History](docs/audit-history.md) — baseline → v1.0.0 improvements trail

## Development

\`\`\`bash
# Run tests
python -m pytest tests/unit tests/integration tests/sdk -q

# Run benchmarks
python scripts/run_benchmark.py

# Security scan
bandit -r src/ sdk/
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
\`\`\`

## Status

**v1.0.0** — technically release-ready. Open items are non-code (PMF validation, AWS secrets setup, paying customers).

See [docs/release-readiness.md](docs/release-readiness.md) for full checklist.

## License

MIT (see LICENSE)

## Credits

Built 2026-04-17 → 2026-04-20 as a data-engineering reference project.
Planning trail in `docs/plans/` — 16 plans, 15 commits, honest history including one incident recovery (v15.5).
```

### Rules

- **НЕ** использовать маркетинговый язык ("revolutionary", "game-changer", "next-gen")
- Числа должны совпадать с `docs/benchmark-baseline.json` и `docs/release-readiness.md`
- Линки — все относительные (репо-local), не absolute URLs
- Badges — placeholder URLs, заменить реальными после публикации

### Verify

```bash
# Markdown валидный
python -c "import re; d=open('README.md').read(); assert len(d) > 2000, 'too short'"

# Все ссылки на docs/ — существуют
python -c "
import re
doc = open('README.md').read()
for link in re.findall(r'\]\(([^)]+)\)', doc):
    if link.startswith(('http', '#')): continue
    from pathlib import Path
    if not Path(link).exists(): print(f'BROKEN: {link}')
print('links checked')
"
```

---

## TASK 2 — `docs/glossary.md` — обучающий файл для автора

**Цель:** объяснить каждый ключевой термин из README Highlights + архитектурные решения простым языком. Это **обучающий материал**, помогающий автору уверенно обсуждать проект на интервью.

### Структура

Для каждого термина — **4 секции:**
1. **Что это** (1-2 предложения, без жаргона)
2. **Как в AgentFlow** (как конкретно реализовано, с ссылкой на код)
3. **Почему это важно** (что бы было без этого)
4. **Что спросит интервьюер** (1-2 типичных follow-up вопроса + как отвечать)

### Термины для покрытия (минимум 15)

**Testing & Quality:**
- **542 tests passing** — unit vs integration vs e2e vs property vs chaos vs contract tests (чем отличаются, зачем все нужны)
- **p50, p95, p99 latency** — что такое перцентили, почему p50 != average, почему p99 критичен
- **Baseline (p50=43ms, was 26 seconds)** — что измеряли, в каких условиях, что означает 600x improvement

**SDK & Resilience:**
- **Dual SDK (Python + TypeScript)** — почему оба, паритет API
- **Resilience patterns: retry with exponential backoff + jitter** — что делает, когда применять
- **Circuit breaker** — 3 состояния (closed/open/half-open), зачем нужен в микросервисах
- **Backwards compatibility in SDK** — почему важна, `configure_resilience()` pattern

**Security:**
- **Parameterized queries** — vs string interpolation, как предотвращают SQL injection
- **sqlglot AST validator** — SQL parser, allowlist подход, отличие от regex
- **Bandit baseline gate** — static analysis, baseline-first approach к legacy code

**CI/CD & Operations:**
- **Chaos testing** — Toxiproxy, что имитирует (network latency, DB restart), PR smoke vs scheduled full
- **Load regression gate** — Locust, % regression threshold, как ловит slowdowns до main
- **Terraform workflow** — IaC, `plan` vs `apply`, manual approval gates, OIDC auth
- **DuckDB + Iceberg architecture** — когда DuckDB подходит (analytics, <100GB), Iceberg (time travel, schema evolution)

**Infrastructure:**
- **Admin UI (FastAPI + Jinja + HTMX)** — почему без React, когда SSR оправдан
- **Landing page** — что показывает без hype
- **Fly.io demo config** — edge deployment, когда применять

### Пример секции

```markdown
## p50, p95, p99 latency

### Что это
Перцентили latency. p50 = медиана (50% запросов быстрее этого значения), p95 = 95% быстрее, p99 = 99% быстрее. p99 показывает худший реалистичный опыт пользователя.

### Как в AgentFlow
Измеряется через Locust в `scripts/run_benchmark.py`. Текущие значения в `docs/benchmark-baseline.json`:
- p50 entity: 43ms
- p99 entity: 290-320ms
- p99 captured отдельно для каждого endpoint.

### Почему это важно
**Average обманывает.** Если 99% запросов — 10ms, а 1% — 30 секунд, average ≈ 300ms выглядит хорошо. Но тот самый 1% = это и есть опыт части пользователей. p99 честнее.

Для AI-агентов p99 особенно критичен: агент может делать 10+ вызовов API за один ответ. Если p99 = 1s, цепочка из 10 вызовов = ~10% шанс что один из них будет медленным → весь agent response тормозит.

### Что спросит интервьюер
- "Почему вы смотрите на p99, а не average?" → ответ выше
- "Что если p99 внезапно скакнул с 170ms до 300ms?" → есть known limitation после v12, задокументирована как acceptable (gate <500ms), followup в v1.1. Это не маскирование — честно в docs.
```

### Deliverable

`docs/glossary.md` — 400-700 строк (15 терминов × ~30-50 строк каждый).

### Verify

```bash
grep -c "^## " docs/glossary.md
# >= 15 терминов

# Каждый термин имеет все 4 секции
python -c "
import re
doc = open('docs/glossary.md').read()
sections = re.split(r'\n## ', doc)[1:]
for s in sections:
    term = s.split('\n')[0]
    for needed in ['Что это', 'Как в AgentFlow', 'Почему это важно', 'Что спросит']:
        if needed not in s: print(f'MISSING {needed} in {term}')
print('glossary structure checked')
"
```

---

## TASK 3 — Secrets audit + `.env.example`

**Цель:** убедиться что в репо нет реальных секретов, admin keys, creds. Создать `.env.example` с placeholder'ами.

### Шаги

```bash
# 1. Scan для типичных patterns
grep -rnE "sk-[a-zA-Z0-9]{20,}|[A-Z0-9]{20}:[a-zA-Z0-9+/]{40}|admin-secret|password.*=.*['\"][^'\"]{6,}" \
  --include="*.py" --include="*.ts" --include="*.yaml" --include="*.yml" \
  src/ sdk/ sdk-ts/ config/ 2>&1 | grep -v "test\|example\|EXAMPLE\|FIXME" | head -20

# 2. Git secrets scan (если установлен)
which truffleHog && truffleHog --regex --entropy=True .

# 3. Проверить что `.env` в .gitignore
grep -E "^\.env$|\.env\s*$" .gitignore
```

### Создать `.env.example`

```bash
# AgentFlow environment variables (copy to .env, fill real values)

# API
DUCKDB_PATH=./agentflow_demo.duckdb
AGENTFLOW_USAGE_DB_PATH=./usage.duckdb
AGENTFLOW_DEMO_MODE=false

# Auth
AGENTFLOW_ADMIN_KEY=<replace-with-strong-random>
AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS=86400

# Cache
REDIS_URL=redis://localhost:6379

# Observability (optional)
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_SERVICE_NAME=agentflow-api

# Production (not needed for local)
# AWS_REGION=us-east-1
# KAFKA_BOOTSTRAP_SERVERS=
```

### Verify

```bash
# Секретов не найдено
# `admin-secret` в тестах — OK (test fixture), но НЕ в production config

test -f .env.example && echo "OK: .env.example exists"
grep -q "^\.env$" .gitignore && echo "OK: .env gitignored"
```

---

## TASK 4 — LICENSE + CONTRIBUTING + release notes

### `LICENSE`

MIT (standard template).

### `CONTRIBUTING.md`

```markdown
# Contributing to AgentFlow

## Development setup
<ссылка на README Quick start>

## Running tests
\`\`\`bash
python -m pytest tests/unit tests/integration tests/sdk -v
\`\`\`

## Before submitting a PR

1. Tests pass: `pytest tests/`
2. Bandit clean: `python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json`
3. Benchmark не регрессит: `python scripts/check_performance.py --baseline docs/benchmark-baseline.json --max-regress 20`
4. Contract drift: `python scripts/generate_contracts.py --check`

## Architecture decisions

Significant changes must include an ADR in `docs/decisions/NNNN-title.md`.
See existing ADRs for format.

## Commit conventions

Follow conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
```

### `CHANGELOG.md` (проектный)

```markdown
# Changelog

All notable changes to AgentFlow.

## [1.0.0] — 2026-04-20

### Added
- Dual SDK (Python + TypeScript) with retry policies and circuit breakers (v14)
- Minimal admin dashboard at `/admin` (v10)
- Chaos smoke on PRs (v10)
- Load regression gate on PRs (v10)
- Terraform apply workflow with environment protection (v10)
- Hosted demo config for Fly.io (v15)
- Full API reference with curl/Python/TS examples (v15)
- Competitive analysis document (v15)
- Security audit report with evidence links (v15)
- v1.1 research: MCP + framework integration patterns (v16)

### Changed
- Performance: entity p50 26000ms → 43ms (~600x improvement). Root cause: sync DuckDB on async endpoints + string interpolation in hot path. Fixed via run_in_threadpool + parameterized queries + Redis cache (v8, v12).
- SQL injection protection: regex-based scoping → sqlglot AST validator. String interpolation → parameterized queries (v8).
- Code structure: split god-classes auth.py (862 LOC), alert_dispatcher.py (738 LOC), query_engine.py (710 LOC) into focused modules <400 LOC each (v8).
- SDK constructor signature cleanup: removed `__signature__` hack, `configure_resilience()` opt-in (v14-cleanup).

### Fixed
- Windows DuckDB file lock in rotation tests (v8-windows-flake)
- Auth auto-revoke regression after auth.py split (v8-followup)
- Analytics hot-path regression: cache stampede + schema re-bootstrap (v12)
- Flink Terraform module: added required `application_code_configuration` (v12)

### Security
- Parameterized queries throughout hot path
- sqlglot AST validator for NL→SQL with table allowlist
- Bandit baseline gate in CI (only new findings fail)
- API key rotation with grace period + auto-revoke
```

### `docs/decisions/0004-v1-publication.md` (ADR)

Короткий ADR про решение остановиться на v1.0.0.

### Verify

```bash
test -f LICENSE && test -f CONTRIBUTING.md && test -f CHANGELOG.md && echo "OK"
```

---

## TASK 5 — Screenshots для README

**Цель:** 3-4 скрина для README (если хочешь добавить inline).

### Что снять

1. **Admin UI** — запустить `make demo`, открыть `http://localhost:8000/admin`, сделать clean скрин
2. **Swagger /docs** — показать список endpoints
3. **Landing page** — `site/index.html` в браузере
4. **Benchmark results** — терминал с выводом `scripts/run_benchmark.py`

Сохранить в `docs/screenshots/`:
- `admin-ui.png`
- `swagger-docs.png`
- `landing-page.png`
- `benchmark-terminal.png`

### Инструкция в README

Показать как:

```markdown
## Screenshots

<table>
<tr>
<td><img src="docs/screenshots/admin-ui.png" alt="Admin UI" width="400"></td>
<td><img src="docs/screenshots/swagger-docs.png" alt="API Docs" width="400"></td>
</tr>
<tr>
<td><img src="docs/screenshots/landing-page.png" alt="Landing" width="400"></td>
<td><img src="docs/screenshots/benchmark-terminal.png" alt="Benchmarks" width="400"></td>
</tr>
</table>
```

### Note

Эту задачу **автор делает сам** (Codex не может запустить GUI + сделать скрин). В плане зафиксировать инструкцию.

---

## TASK 6 — Final pre-publication checklist

Создать `docs/publication-checklist.md`:

```markdown
# GitHub Publication Checklist

Before running `git push` to public repo:

## Content
- [ ] README.md публикационная версия готова
- [ ] LICENSE файл добавлен (MIT)
- [ ] CHANGELOG.md с v1.0.0 entry
- [ ] CONTRIBUTING.md
- [ ] .env.example без реальных секретов
- [ ] docs/glossary.md для обучения автора

## Security
- [ ] grep по репо на secrets — чисто
- [ ] .env в .gitignore
- [ ] .bandit-baseline.json присутствует (не трогать при публикации)
- [ ] agentflow_*.duckdb в .gitignore (data files не должны быть в репо)

## Links
- [ ] Все internal links в README работают
- [ ] Нет absolute URLs на localhost
- [ ] Нет ссылок на D:\... абсолютных путей

## Screenshots (опционально)
- [ ] docs/screenshots/ заполнен (см. Task 5)

## Repo settings (после push)
- [ ] Description в About секции
- [ ] Topics: data-engineering, real-time, ai-agents, fastapi, duckdb, kafka, flink
- [ ] "Releases" → create v1.0.0 с release notes из CHANGELOG

## Verification после publish
- [ ] Clone свежей копии → `make setup && make demo` работает
- [ ] Tests pass на чистом clone
- [ ] Ссылки из README на файлы разрешаются
```

---

## Done When

- [ ] `README.md` публикационный, все ссылки работают
- [ ] `docs/glossary.md` с 15+ терминами, каждый имеет 4 секции
- [ ] `.env.example` создан
- [ ] `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md` созданы
- [ ] `docs/publication-checklist.md` создан
- [ ] Нет секретов в репо (secrets audit passed)
- [ ] Screenshots инструкция зафиксирована (автор сделает сам)
- [ ] Все tests still passing (543)
- [ ] Git commit: "docs: publication preparation for v1.0.0 release"

## Notes

- **НЕ пушить никуда** — только local commits. Публикация — действие автора, не Codex.
- **Не менять** логику кода в `src/`, `sdk/`, `sdk-ts/`. Только docs + config.
- **Glossary** — самый важный deliverable для автора. Codex должен объяснять **как учителю**: без жаргона там где можно, с честными "что бы без этого не работало".
- Если какой-то термин в glossary получается сухим — добавить **аналогию из реальной жизни** (например, circuit breaker = "электрический автомат в доме — выбивает когда замыкание").
