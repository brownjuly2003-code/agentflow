# T03 — E2E Tests workflow: trim docker-compose stack

**Priority:** P1 · **Estimate:** 2-3ч

## Goal

CI workflow `E2E Tests` (`.github/workflows/e2e.yml`) timeout-ится через ~3:13 потому что `docker-compose.prod.yml` поднимает слишком тяжёлый stack для GitHub runner-а (стандартный ubuntu-latest = 7GB RAM, 2 CPU). Создать lite-вариант docker-compose, нацеленный на E2E-минимум (API + Redis + Kafka KRaft + Postgres), и переключить workflow на него.

## Context

- `docker-compose.prod.yml` (production-like) поднимает: API, Redis, Kafka KRaft, Zookeeper(?), Postgres, Iceberg/MinIO, Flink JobManager+TaskManager, Dagster, Prometheus, Grafana, Jaeger. На runner-е это >7GB и долго стартует.
- Тесты в `tests/e2e/` нужны: API (`/v1/*`), Redis (rate limit), Kafka (event ingestion), Postgres/DuckDB (state). НЕ нужны: Flink, Dagster, Iceberg/MinIO, Prometheus/Grafana/Jaeger — это observability/processing стороны, отдельно тестируются.
- `tests/e2e/conftest.py` строит окружение через subprocess; смотрит на `docker-compose.prod.yml`. Не привязан жёстко — параметризован через env vars (`AGENTFLOW_E2E_BASE_URL` и т.д.).
- Тесты должны иметь маркеры `requires_docker` и тонкий пропуск, если stack не поднялся.
- Memory note (см. `~/.claude/projects/D--/memory/project_de_project.md`): "CI E2E Tests — docker-compose.prod.yml timing out, stack too big. Пре-existing."

## Deliverables

1. Создать `docker-compose.e2e.yml` в корне репо. Сервисы — только то, что трогается в `tests/e2e/`:
   - `agentflow-api` (build из текущего Dockerfile)
   - `redis` (`redis:7.4-alpine`, без persistence)
   - `kafka` (`confluentinc/cp-kafka:7.7.0` в KRaft режиме, single broker, без Zookeeper)
   - `postgres` (`postgres:16-alpine`, ephemeral) — если e2e тесты используют. Если нет — пропустить.
   - Healthchecks на все three deps (`pg_isready`, `redis-cli ping`, kafka `kafka-topics --list`).
   - API depends_on с `condition: service_healthy`.
   - Resource limits через `deploy.resources.limits` чтобы не съесть всё на runner-е (например, kafka heap=512MB).
2. В `.github/workflows/e2e.yml` шаг подъёма stack-а заменить на `docker-compose.e2e.yml`. Уменьшить timeout-минут до разумного (например, 12). Добавить wait-loop с `docker compose ps --format json` который ждёт `health: healthy` для key services перед запуском тестов.
3. На failure — собрать логи всех сервисов:
   ```yaml
   - name: Capture compose logs on failure
     if: failure()
     run: docker compose -f docker-compose.e2e.yml logs --tail=500
   ```
4. Локально (если есть Docker): `docker compose -f docker-compose.e2e.yml up -d --wait` поднимает stack за <90 сек, `pytest tests/e2e/ -v` зелёный.
5. Один коммит: `ci(e2e): use lighter docker-compose for E2E suite`. Если в процессе нашлись тесты, которые требуют Flink/Iceberg/etc — не тащить тяжёлые сервисы обратно, **исключить эти тесты** из E2E job-а через `pytest -k "not requires_flink"` или маркер, и задокументировать в commit message «excluded N tests requiring heavy stack: <список>».

## Acceptance

- `E2E Tests` workflow зелёный на push в main, время выполнения <12 мин (vs текущие >3:13 timeout).
- Локально: `docker compose -f docker-compose.e2e.yml up -d --wait` за <90 сек на 8GB RAM machine, `pytest tests/e2e/ -v` зелёный (или внятно skipped с reason для исключённых).
- `docker stats` показывает суммарное использование <5GB во время E2E run.
- На failure CI шаг — все service logs в Actions output.

## Notes

- НЕ удалять `docker-compose.prod.yml` — его юзают разработчики для full local development, и он используется в Trivy security scan для production-like image build.
- НЕ добавлять Flink/Dagster в lite compose — даже если какой-то тест их требует, изолировать его маркером и отдельным workflow `processing-e2e.yml` (вне scope этого таска, отдельный PR при необходимости).
- KRaft Kafka стартует за ~15-20 сек, Zookeeper-based — 40-60 сек. KRaft → быстрее.
- Если Kafka health check сложный — можно пробовать `confluentinc/cp-kafka:7.7.0` с `KAFKA_PROCESS_ROLES=broker,controller` и опросом `kafka-broker-api-versions`.
- Backstop: если lite compose не получается стабильным — оставить `docker-compose.prod.yml` но с `--profile minimal` и selectively включёнными сервисами через `profiles:` блок.
