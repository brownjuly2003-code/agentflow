# AgentFlow Glossary

This file explains the technical terms used in the public README and release notes. It is written as interview prep for the project author: first in plain language, then with the exact place where the concept appears in AgentFlow, then with the reason it matters.

## 668 full-suite tests passing (last completed gate)

### Что это
Это текущий размер полного локального тестового gate: сколько автотестов прогоняется, чтобы убедиться, что проект не сломался в базовых и расширенных сценариях. Важно не само красивое число, а то, что тесты покрывают разные слои системы, а не только отдельные функции.

### Как в AgentFlow
В AgentFlow последний полный локальный gate запускает `python -m pytest -p no:schemathesis -q --tb=short --durations=30 --timeout=300` с Redis и project-local temp paths; последний завершённый локальный full-suite gate на 2026-04-27 дал `668 passed, 8 skipped`. Текущий fresh pre-commit gate заблокирован chaos smoke hang, см. `docs/release-readiness.md`. Основные директории: [tests/unit](../tests/unit), [tests/integration](../tests/integration), [tests/sdk](../tests/sdk), [tests/contract](../tests/contract), [tests/property](../tests/property), [tests/chaos](../tests/chaos), [tests/e2e](../tests/e2e). Релизный статус и команда верификации зафиксированы в [release-readiness.md](release-readiness.md).

### Почему это важно
Одни тесты проверяют маленькие функции, другие проверяют весь путь запроса через API, третьи проверяют SDK как внешний контракт для пользователя. Если оставить только unit-тесты, можно пропустить ситуацию, где каждая часть по отдельности работает, но связка между ними уже нет.

### Что спросит интервьюер
- "Почему вы не ограничились unit-тестами?" -> Потому что API, SDK и интеграции ломаются чаще всего на стыках модулей, а не внутри одного `if`.
- "663 - это много или мало?" -> Само по себе число ничего не гарантирует; важно, что тесты разделены по типам риска и реально закрывают релизный путь.

## p50, p95, p99 latency

### Что это
Это перцентили времени ответа. `p50` - медиана, то есть половина запросов быстрее этого значения. `p95` и `p99` показывают хвост задержек: насколько медленными становятся не типичные, а худшие реалистичные запросы.

### Как в AgentFlow
Benchmarks собираются через [scripts/run_benchmark.py](../scripts/run_benchmark.py) и профиль нагрузки из [tests/load/locustfile.py](../tests/load/locustfile.py). Зафиксированный baseline лежит в [benchmark-baseline.json](benchmark-baseline.json): aggregate `p50=56 ms`, `p95=260 ms`, `p99=330 ms`; по entity endpoints `p50=38-55 ms`, `p99=290-320 ms`.

### Почему это важно
Average легко маскирует проблему. Если почти все запросы быстрые, а редкие запросы очень медленные, среднее значение выглядит "нормально", хотя пользователь всё равно периодически утыкается в длинные паузы. Для AI-агента это особенно важно: один ответ может включать несколько API-вызовов подряд, и именно хвост задержек замедляет весь диалог.

### Что спросит интервьюер
- "Почему вы смотрите на p99, а не на average?" -> Потому что average скрывает плохие хвосты, а p99 показывает реальный worst-case для живого пользователя.
- "Что важнее: p50 или p99?" -> Оба. `p50` показывает типичный опыт, `p99` показывает, насколько неприятны редкие плохие случаи.

## Baseline и улучшение с ~26 000 ms до release-range

### Что это
Baseline - это зафиксированная точка сравнения. Она нужна, чтобы сравнивать новые прогоны не с ощущением "кажется стало лучше", а с конкретным числом, сохранённым в репозитории.

### Как в AgentFlow
Историческая линия собрана в [audit-history.md](audit-history.md): там видно, что ранний baseline был около `26 000 ms` по entity p50, а после исправлений v8-v12 путь стал работать в диапазоне `43-55 ms`. Текущий baseline закреплён в [benchmark-baseline.json](benchmark-baseline.json), а gate сравнения реализован в [scripts/check_performance.py](../scripts/check_performance.py).

### Почему это важно
Такой baseline делает performance claim проверяемым. Он также защищает от самообмана: если исторически было `43 ms`, а текущий checked-in baseline уже `55 ms`, это надо честно сказать в документации, а не продолжать цитировать старое красивое число как будто ничего не изменилось.

### Что спросит интервьюер
- "За счёт чего был такой большой скачок?" -> За счёт ремонта hot path: async offload, параметризованные запросы, кеш и пересмотр serving-path bottleneck'ов.
- "Почему вы пишете диапазон `43-55 ms`, а не одно число?" -> Потому что `43 ms` - важный исторический этап, а checked-in release baseline сейчас честно показывает `38-55 ms` по entity endpoints.

## Dual SDK (Python + TypeScript)

### Что это
Dual SDK означает, что проект даёт клиентские библиотеки сразу для двух основных экосистем. Идея не в том, чтобы написать два разных продукта, а в том, чтобы один и тот же API был удобен и для backend/agent кода на Python, и для TypeScript/Node/browser-потребителей.

### Как в AgentFlow
Python-клиент живёт в [sdk/agentflow/client.py](../sdk/agentflow/client.py), TypeScript-клиент - в [sdk-ts/src/client.ts](../sdk-ts/src/client.ts). Оба клиента умеют вызывать тот же HTTP surface: entity lookup, metrics, query, catalog, batch и потоковые события. Паритет дополнительно страхуется тестами из [tests/sdk](../tests/sdk) и контрактами в [config/contracts](../config/contracts).

### Почему это важно
Если у тебя агентные workflow живут в разных средах, отсутствие официального SDK быстро превращается в ручные fetch/httpx-обвязки, которые расходятся между командами. Dual SDK удерживает один контракт и снижает риск того, что Python-клиент умеет одно, а TypeScript-клиент - другое.

### Что спросит интервьюер
- "Почему вообще понадобились оба SDK?" -> Потому что Python типичен для agent/backoffice workflow, а TypeScript часто нужен для web, edge и Node-интеграций.
- "Как вы удерживаете паритет?" -> Через единый HTTP contract, tests и version-aware schema contracts.

## Retry with exponential backoff + jitter

### Что это
Retry - это повтор запроса после сбоя. Exponential backoff означает, что пауза между попытками растёт: сначала маленькая, потом больше. Jitter - это случайное отклонение этой паузы, чтобы много клиентов не начали повторять запрос одновременно и не устроили новый всплеск нагрузки.

### Как в AgentFlow
Python-реализация находится в [sdk/agentflow/retry.py](../sdk/agentflow/retry.py), TypeScript-версия - в [sdk-ts/src/retry.ts](../sdk-ts/src/retry.ts). В Python `RetryPolicy.compute_delay()` считает задержку на основе `initial_delay_s`, `max_delay_s` и `jitter_factor`. Ретрай разрешён для идемпотентных методов и для `POST` только если есть `idempotency-key`.

### Почему это важно
Не every failure означает "сломалось навсегда". Бывают сетевые дёргания, краткий `429`, временный `503`. Retry помогает пережить такие короткие проблемы без ручного вмешательства, но делает это осторожно, чтобы не усилить аварию.

### Что спросит интервьюер
- "Почему не ретраить всё подряд?" -> Потому что неидемпотентный повтор может создать дубликаты или повторить опасное действие.
- "Зачем нужен jitter?" -> Чтобы тысяча клиентов не проснулась через одинаковые `500 ms` и не ударила сервис второй волной.

## Circuit breaker

### Что это
Circuit breaker - это защитный автомат для удалённого вызова. Пока всё нормально, он в состоянии `closed` и пропускает запросы. Когда подряд идёт слишком много ошибок, он "выбивает" в `open` и на время перестаёт даже пытаться стучаться в проблемный сервис. Потом он даёт одну пробную попытку в `half-open`.

### Как в AgentFlow
Состояния и переходы видно в [sdk/agentflow/circuit_breaker.py](../sdk/agentflow/circuit_breaker.py): `CLOSED`, `OPEN`, `HALF_OPEN`. Клиент вызывает `before_call()`, а затем `record_success()` или `record_failure()`. Аналогичная логика есть и в TypeScript-версии в [sdk-ts/src/circuitBreaker.ts](../sdk-ts/src/circuitBreaker.ts).

### Почему это важно
Без такого механизма клиент во время инцидента продолжает спамить уже падающий сервис. Это вредно и для клиента, и для сервера. Circuit breaker делает поведение более "вежливым": сначала фиксирует деградацию, потом берёт паузу, потом осторожно проверяет, ожил ли сервис.

### Что спросит интервьюер
- "Чем breaker отличается от retry?" -> Retry пытается пережить короткий сбой, а breaker защищает систему от постоянного битья в уже мёртвый dependency.
- "Почему аналогия с автоматом в доме уместна?" -> Потому что логика похожа: при перегрузке цепь временно размыкается, а потом проверяется заново.

## Backwards compatibility и `configure_resilience()`

### Что это
Backwards compatibility - это способность обновить библиотеку, не ломая существующий код пользователя. Иногда API нужно улучшить, но если сделать это жёстко, все клиенты вынуждены мгновенно переписываться.

### Как в AgentFlow
В [sdk/agentflow/client.py](../sdk/agentflow/client.py) публичный конструктор остаётся компактным: `base_url`, `api_key`, `timeout`, `contract_version`. При этом legacy-параметры resilience всё ещё поддерживаются через совместимый слой, который внутри вызывает `configure_resilience()`. Это поведение и сама сигнатура закреплены тестами в [tests/unit/test_sdk_backwards_compat.py](../tests/unit/test_sdk_backwards_compat.py).

### Почему это важно
SDK - это внешний интерфейс проекта. Даже если внутри ты всё переделал правильно, ломающая сигнатура в клиенте превращает "обновление" в неприятный миграционный проект для каждого пользователя. Совместимость снижает стоимость апдейта.

### Что спросит интервьюер
- "Почему не сломать API и не начать заново?" -> Потому что у SDK есть потребители; чистота внутренней реализации не должна перекладывать миграционную цену на них без серьёзной причины.
- "Как вы проверяете, что совместимость действительно сохранена?" -> Через тесты на публичную сигнатуру, экспортируемые методы и семантику deprecated-path.

## Typed contracts и versioning

### Что это
Контракт - это формальное описание того, какие поля, типы и версии данных разрешены. Versioning нужен, чтобы схема могла меняться без тихой поломки клиентов.

### Как в AgentFlow
Контракты лежат в [config/contracts](../config/contracts), загружаются через [src/serving/semantic_layer/contract_registry.py](../src/serving/semantic_layer/contract_registry.py) и генерируются из моделей скриптом [scripts/generate_contracts.py](../scripts/generate_contracts.py). Registry умеет отдавать latest stable, конкретную версию и diff с классификацией на breaking/additive changes. SDK может пиновать нужную версию контракта перед валидацией ответа.

### Почему это важно
Для агентов schema drift особенно болезнен. Если поле исчезло или поменяло тип, LLM-обвязка и downstream code часто падают не сразу и не очевидно. Контракт делает изменение явным: либо версия не совпала, либо diff показал, что изменение breaking.

### Что спросит интервьюер
- "Почему не ограничиться Pydantic-моделями?" -> Потому что нужен внешний, сериализуемый, versioned contract, доступный API и SDK независимо от внутреннего Python-кода.
- "Что даёт diff контрактов?" -> Возможность явно сказать, что поменялось: добавили поле безопасно или сломали старый consumer.

## Parameterized queries

### Что это
Параметризованный запрос отделяет структуру SQL от пользовательского значения. В текст запроса ставится placeholder, а реальное значение передаётся отдельно.

### Как в AgentFlow
Backend интерфейс принимает `sql` и `params` в [src/serving/backends/duckdb_backend.py](../src/serving/backends/duckdb_backend.py). В entity lookup путь использует `?` placeholders в [src/serving/semantic_layer/query/entity_queries.py](../src/serving/semantic_layer/query/entity_queries.py). Отдельные инъекционные кейсы покрыты в [tests/unit/test_query_engine_injection.py](../tests/unit/test_query_engine_injection.py).

### Почему это важно
Если подставлять строку пользователя прямо внутрь SQL, атакующий может подменить смысл запроса. Параметризация передаёт значение как данные, а не как часть SQL-команды, и этим закрывает классический путь к SQL injection.

### Что спросит интервьюер
- "Где в SQL всё ещё остаётся string interpolation?" -> Только там, где строка не приходит от пользователя, а берётся из внутреннего allowlist-каталога, например имя таблицы из метаданных.
- "Почему это важнее именно в hot path?" -> Потому что hot path - это самый вызываемый путь; если он небезопасен, риск и поверхность атаки растут многократно.

## `sqlglot` AST validator

### Что это
AST validator сначала парсит SQL в дерево, а потом проверяет это дерево по правилам: какие типы команд разрешены, к каким таблицам можно обращаться, нет ли опасных конструкций. Это намного надёжнее, чем проверять SQL регулярками.

### Как в AgentFlow
В [src/serving/semantic_layer/sql_guard.py](../src/serving/semantic_layer/sql_guard.py) функция `validate_nl_sql()` разрешает только один `SELECT`, запрещает DDL/DML-узлы (`DROP`, `DELETE`, `UPDATE` и т.д.), учитывает CTE aliases и проверяет, что реальные таблицы входят в allowlist. Это и есть защитный фильтр для NL-to-SQL пути.

### Почему это важно
Regex не понимает структуру SQL. Он легко ломается на CTE, подзапросах, комментариях и экранировании. Парсер, наоборот, видит именно синтаксическое дерево и позволяет проверять не "есть ли подозрительная подстрока", а "что этот запрос реально пытается сделать".

### Что спросит интервьюер
- "Почему regex недостаточно?" -> Потому что SQL - это грамматика, а не просто строка; регулярка не умеет надёжно отличать harmless текст от опасной конструкции.
- "Можно ли после такого валидатора использовать CTE и joins?" -> Да, если итоговый запрос остаётся `SELECT` и трогает только разрешённые таблицы.

## Bandit baseline gate

### Что это
Это подход "не пускаем новые security findings, но не делаем вид, что старых не существует". Baseline хранит уже известные результаты, а gate падает только тогда, когда появляется новое предупреждение.

### Как в AgentFlow
Скан запускается в [../.github/workflows/security.yml](../.github/workflows/security.yml). Скрипт [../scripts/bandit_diff.py](../scripts/bandit_diff.py) сравнивает текущий JSON-репорт с [../.bandit-baseline.json](../.bandit-baseline.json) и завершает job ошибкой, если появляются новые issue keys по `test_id`, файлу и номеру строки.

### Почему это важно
На зрелом проекте редко получается разом починить весь исторический security debt. Baseline-first подход даёт реалистичную дисциплину: старые долги видны и задокументированы, но новые долги больше не допускаются.

### Что спросит интервьюер
- "Раз baseline не скрывает уже известные проблемы?" -> Он не скрывает, а фиксирует их как текущий остаток долга; новые находки всё равно режут CI.
- "Почему это лучше, чем требовать ноль finding'ов сразу?" -> Потому что иначе команда либо отключит скан, либо будет жить в перманентно красном CI.

## Chaos testing

### Что это
Chaos testing - это намеренное создание поломок в зависимостях, чтобы увидеть, как система деградирует в реальности. Идея не "сломать ради шоу", а заранее доказать, что сервис ведёт себя предсказуемо при частичных авариях.

### Как в AgentFlow
Локальный chaos stack описан в [../docker-compose.chaos.yml](../docker-compose.chaos.yml), сетевые сбои моделируются через [../config/toxiproxy.json](../config/toxiproxy.json), smoke-сценарии лежат в [../tests/chaos/test_chaos_smoke.py](../tests/chaos/test_chaos_smoke.py), а CI-логика разделяет PR smoke и scheduled full run в [../.github/workflows/chaos.yml](../.github/workflows/chaos.yml).

### Почему это важно
Graceful degradation нельзя доказать только код-ревью и happy-path тестами. Пока ты не симулировал timeout у DuckDB proxy или недоступность Redis, ты не знаешь, как поведёт себя система под реальным сбоем.

### Что спросит интервьюер
- "Почему на PR идёт только smoke, а не весь chaos suite?" -> Потому что PR должен оставаться достаточно быстрым, а полный прогон дороже и подходит для scheduled verification.
- "Что именно вы проверяете хаосом?" -> Что API отдаёт ожидаемые ошибки, кеш корректно деградирует, а система не зависает в непредсказуемом состоянии.

## Load regression gate

### Что это
Это проверка, которая не просто запускает нагрузочный тест, а сравнивает новый результат с baseline и режет PR при заметной деградации. То есть performance становится частью definition of done, а не послерелизной надежды.

### Как в AgentFlow
Профиль нагрузки живёт в [../tests/load/locustfile.py](../tests/load/locustfile.py): entity lookups, metric queries, NL query, batch и health. Сравнение baseline/current выполняет [../scripts/check_performance.py](../scripts/check_performance.py), а PR-job оформлен в [../.github/workflows/perf-regression.yml](../.github/workflows/perf-regression.yml). Gate учитывает и относительную деградацию, и абсолютный порог для entity latency.

### Почему это важно
Регресс производительности часто не выглядит как "всё сломалось". Он выглядит как "стало чуть медленнее", потом ещё чуть, и через несколько недель API уже неприятный. Gate ловит это до merge в `main`.

### Что спросит интервьюер
- "Почему мало абсолютного SLA?" -> Потому что абсолютный порог не замечает медленное сползание внутри допустимого окна.
- "Почему мало только относительного сравнения?" -> Потому что можно стабильно сравниваться с уже плохим baseline; нужен и абсолютный sanity check.

## Terraform workflow: `plan`, `apply`, OIDC

### Что это
Terraform описывает инфраструктуру как код. `plan` показывает, что изменится, а `apply` применяет изменения. OIDC позволяет GitHub Actions получать облачные креды без статических long-lived secret keys.

### Как в AgentFlow
Основной IaC лежит в [../infrastructure/terraform](../infrastructure/terraform). Workflow [../.github/workflows/terraform-apply.yml](../.github/workflows/terraform-apply.yml) делает отдельный `plan`, сохраняет артефакт `tfplan`, а затем даёт `apply` только после environment-gated шага. AWS-доступ настраивается через `aws-actions/configure-aws-credentials` и `role-to-assume`.

### Почему это важно
Инфраструктура - такая же часть системы, как код. Если деплой делать руками, знание остаётся в головах, а не в репозитории. Разделение `plan/apply` плюс approval делает изменения видимыми и безопаснее.

### Что спросит интервьюер
- "Почему `apply` не автоматический?" -> Потому что инфраструктурные изменения дороже ошибки; ручное подтверждение здесь осознанно.
- "Что ещё осталось ручным?" -> GitHub environments и AWS OIDC role wiring всё ещё требуют настройки со стороны владельца репозитория.

## DuckDB + Iceberg architecture

### Что это
DuckDB - лёгкая columnar база для локальной аналитики и быстрых single-node чтений. Iceberg - это table format для больших аналитических данных с time travel, snapshot-ами и schema evolution.

### Как в AgentFlow
Архитектурный контекст описан в [architecture.md](architecture.md). Локальный serving path использует [../src/serving/backends/duckdb_backend.py](../src/serving/backends/duckdb_backend.py), а local pipeline пишет demo-данные через [../src/processing/local_pipeline.py](../src/processing/local_pipeline.py). Production-shaped путь ориентируется на Iceberg и его каталоги/таблицы.

### Почему это важно
Эта связка позволяет не выбирать между "удобно локально" и "похоже на прод". DuckDB даёт быстрый dev/demo loop, а Iceberg оставляет дверь в production-friendly lakehouse path с time travel и управляемой эволюцией схемы.

### Что спросит интервьюер
- "Когда DuckDB подходит?" -> Когда нужен быстрый локальный или single-node serving/analytics path без отдельного кластера.
- "Когда уже нужен Iceberg?" -> Когда важны snapshot semantics, schema evolution, большой объём данных и production-shaped storage layout.

## Admin UI (FastAPI + Jinja, server-rendered)

### Что это
Это минимальный операционный интерфейс, который показывает состояние системы, usage и health без отдельного тяжёлого frontend stack. По сути, это read-only dashboard для администратора.

### Как в AgentFlow
Роуты лежат в [../src/serving/api/routers/admin_ui.py](../src/serving/api/routers/admin_ui.py), шаблон - в [../src/serving/api/templates/admin.html](../src/serving/api/templates/admin.html), поведение проверяется тестами из [../tests/integration/test_admin_ui.py](../tests/integration/test_admin_ui.py). Страница собирает health, cache stats, db pool stats и usage, а summary обновляется периодическим partial-refresh.

### Почему это важно
Для такой поверхности React не обязателен. Если интерфейс в основном читает данные и не требует сложного client-side state, server-rendered страница быстрее появляется, проще поддерживается и не требует второй крупной системы внутри проекта.

### Что спросит интервьюер
- "Почему не React?" -> Потому что здесь нужен небольшой ops dashboard, а не отдельное frontend-приложение со сложным интерактивным состоянием.
- "Когда SSR-подход перестанет хватать?" -> Когда появится тяжёлая интерактивность, сложная клиентская маршрутизация или большой объём client-side state transitions.

## Landing page и Fly.io demo config

### Что это
Landing page - это публичная страница, которая быстро объясняет проект человеку, не открывая сразу десятки markdown-файлов. Fly.io demo config - это минимальный deploy path, чтобы поднять демонстрационный инстанс без полной production-инфраструктуры.

### Как в AgentFlow
Публичная страница лежит в [../site/index.html](../site/index.html). Там зафиксированы проблема, user journeys, ключевые differentiators и baseline numbers без hype. Hosted demo path описан в [../deploy/fly/fly.toml](../deploy/fly/fly.toml) и [../deploy/fly/README.md](../deploy/fly/README.md): volume mount для DuckDB, health check на `/v1/health`, минимальная конфигурация для single-app demo.

### Почему это важно
Для публичного GitHub-репозитория мало иметь хороший код. Нужен ещё короткий входной слой: "что это", "зачем это существует", "как быстро посмотреть". Landing page решает narrative side, а Fly config решает demo side.

### Что спросит интервьюер
- "Почему Fly.io?" -> Потому что для демо это простой hosted path с понятной конфигурацией и persistent volume, без разворачивания всей production topology.
- "Это production deployment?" -> Нет, это demo path. Полный production-shaped story в проекте шире и строится вокруг Terraform, Helm и streaming stack.
