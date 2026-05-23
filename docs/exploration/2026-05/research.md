# Research: интерактивное техническое описание AgentFlow

Дата: 2026-05-06  
Контекст: AgentFlow, HEAD локального репозитория при исследовании `577651c`

## Executive Summary

Лучшее решение для AgentFlow сейчас: **MkDocs Material как основной docs-as-code сайт + Diataxis/arc42 для структуры + C4 для архитектурной модели + Mermaid/D2 для диаграмм + Slidev для интерактивного технического тура**.

Почему: в репозитории уже есть сильная Markdown-база (`docs/architecture.md`, `docs/api-reference.md`, `docs/runbook.md`, `docs/openapi.json`, ADR-папка, SDK, Terraform/Helm/K8s). MkDocs минимально инвазивен для Python-проекта, собирает статический HTML, хорошо работает локально, поддерживает Mermaid в Material, не требует платного SaaS и не вынуждает переносить документацию в React-приложение. Slidev закрывает интерактивную/анимированную презентацию для архитектурного walkthrough без превращения основного docs-сайта в слайд-деку.

Запасной минимальный стек: **GitHub Markdown + Mermaid + README navigation + существующий FastAPI Swagger/OpenAPI**. Это почти нулевая стоимость внедрения, но хуже визуально, слабее по навигации и не дает полноценного интерактивного объяснения.

Строгая граница claims: документация должна говорить, что локальные тесты и quality gates зелёные, но не должна заявлять внешний pen-test, AWS OIDC apply или immutable WORM retention как завершенные без внешнего evidence.

## Источники И Выводы

### Подходы и стандарты

Высокая уверенность:

- **C4 model** подходит как визуальная модель: официальный C4 описывает уровни system context, container, component, code и дополнительные dynamic/deployment diagrams; также прямо говорит, что обычно достаточно не всех уровней, а только тех, что добавляют ценность. Источник: https://c4model.com/diagrams
- **arc42** подходит как оглавление глубокой архитектурной документации: цели, constraints, context/scope, solution strategy, building blocks, runtime, deployment, crosscutting concepts, decisions, quality, risks, glossary. Источник: https://arc42.org/overview
- **ADR** подходит для объяснения “почему выбрали Kafka/Flink/Iceberg/DuckDB/FastAPI/etc.”: ADR фиксирует архитектурное решение, rationale, trade-offs, consequences. Источник: https://adr.github.io/
- **Diataxis** подходит для информационной архитектуры docs-сайта: tutorials, how-to guides, reference, explanation. Источник: https://diataxis.fr/

Inference для AgentFlow: C4 отвечает “как устроено”, arc42 отвечает “что обязательно покрыть”, Diataxis отвечает “как разложить по пользовательским задачам”, ADR отвечает “почему так”.

### Инструменты диаграмм и docs-as-code

Высокая уверенность:

- **MkDocs**: Python-friendly static site generator для Markdown-документации, с live dev-server и static HTML export. Источник: https://www.mkdocs.org/
- **Material for MkDocs**: нативно интегрируется с Mermaid code blocks, включая flowchart, sequence, state, class, ER diagrams. Источник: https://squidfunk.github.io/mkdocs-material/reference/diagrams/
- **Mermaid**: диаграммы из Markdown-inspired text definitions; цель Mermaid - помочь документации догонять разработку. Источник: https://mermaid.js.org/intro/
- **D2**: декларативный язык “text to diagrams”, CLI offline workflow, SVG/PNG/PDF export, interactive tooltips/links, themes, containers, sequence diagrams, animations. Источник: https://d2lang.com/
- **Structurizr DSL/Lite**: reference implementation для C4, models-as-code, free/open-source local Docker, interactive diagrams, CLI export в PlantUML/Mermaid/static site/PNG/SVG. Источник: https://docs.structurizr.com/ и https://docs.structurizr.com/dsl
- **Docusaurus**: React/MDX static site generator, сильный для интерактивных React-компонентов, но тяжелее для текущего Python-first репозитория. Источник: https://docusaurus.io/docs
- **Slidev**: developer slides from Markdown, MIT, поддерживает click animations, transitions, motion, Mermaid, export PDF/PPTX/PNG/Markdown. Источники: https://sli.dev/ и https://sli.dev/guide/exporting.html
- **Reveal.js**: open-source HTML presentation framework, Markdown support, Auto-Animate, PDF export, speaker notes, JS API. Источник: https://revealjs.com/

### Видео/анимация

Средняя/высокая уверенность:

- **Motion Canvas**: free/open-source TypeScript library + editor для informative vector animations, real-time preview, image sequence/FFmpeg rendering. Хорош для 1-2 polished video scenes, но требует ручной TS-анимации. Источник: https://motioncanvas.io/docs/
- **Manim**: free/open-source Python library for mathematical animations, MIT. Хорош для алгоритмических/математических объяснений, но для data platform architecture обычно тяжелее и менее web-native. Источник: https://www.manim.community/
- **D3**: JavaScript library for bespoke data visualization with interactions such as panning, zooming, brushing, dragging. Хорош для кастомного интерактивного graph explorer, но это разработка UI, а не документация “из коробки”. Источник: https://d3js.org/
- **Remotion**: сильный React-video инструмент, но не подходит как обязательная бесплатная часть: официальный license page говорит, что free только для individuals, for-profit orgs up to 3 employees, nonprofits или evaluation; иначе нужна company license. Источник: https://www.remotion.dev/docs/license
- **Lottie**: open-source vector animation format/player, но типично требует design-authoring pipeline вроде After Effects/Bodymovin. Для AgentFlow это лишняя ручная поддержка без явной пользы. Источники: https://lottie.github.io/ и https://github.com/airbnb/lottie-web

### Генерация документации из репозитория

Подходящие OSS-инструменты:

- **FastAPI/OpenAPI + Swagger UI/Redoc**: у AgentFlow уже есть `docs/openapi.json`; Swagger UI генерирует интерактивную документацию из OpenAPI/Swagger spec. Источники: https://github.com/swagger-api/swagger-ui и https://swagger.io/docs/specification/v3_0/about/
- **mkdocstrings**: автогенерация Python API reference внутри MkDocs. Источник: https://mkdocstrings.github.io/
- **TypeDoc**: генерирует HTML docs или JSON model из TypeScript source comments. Источник: https://typedoc.org/
- **terraform-docs**: генерирует документацию Terraform modules в разных форматах. Источник: https://terraform-docs.io/
- **helm-docs**: генерирует Markdown-документацию для Helm charts. Источник: https://github.com/norwoodj/helm-docs
- **Pyreverse/Pylint**: извлекает UML class/package diagrams из Python, но для AgentFlow это скорее вспомогательный низкоуровневый artifact, не основная архитектурная карта. Источник: https://www.pylint.org/diagrams/
- **Diagrams (mingrammer)**: Python diagrams-as-code для cloud/system architecture, полезен для infra overview, но требует Graphviz и конкурирует с C4/D2. Источник: https://github.com/mingrammer/diagrams
- **Kroki**: unified diagram rendering API для Mermaid, PlantUML, D2, Structurizr и др.; можно self-host, но как обязательная часть не нужен, потому что MkDocs + Mermaid/D2 CLI проще. Источник: https://docs.kroki.io/kroki/

Inference: полностью автоматическая генерация “архитектурного объяснения” из репозитория ненадежна. Автогенерацию стоит использовать только для reference sections: API, SDK, Terraform, Helm. Системные trade-offs, out-of-scope и external-gate disclaimers должны быть curated вручную.

### Codex/Claude skills, MCP servers, plugins

Локально релевантные skills:

- `technical-writing`: подходит для architecture docs, API docs, runbooks.
- `research-synthesis`: подходит для сводки источников.
- `doc-consolidation`: может помочь перенести уже существующие docs в единую структуру.
- `make-pdf`: может пригодиться для PDF-публикации, но не должен быть основной зависимостью.
- `browser`/`playwright`/`webapp-testing`: подходят для QA собранного static site.
- `imagemagick-local`: только для постобработки raster assets, не для основной документации.

MCP:

- Официальные MCP servers `filesystem`, `git`, `github` полезны для чтения repo, git history и GitHub metadata, но не являются генераторами архитектурной документации. Источник: https://github.com/modelcontextprotocol/servers
- Context7/GitMCP могут подтягивать актуальные docs библиотек, но это не должно быть build-time dependency и не нужно для reproducible zero-budget сайта.
- MCP в этом проекте лучше считать assistant-time tooling, а не частью deliverable.

OSS/AI repo tools:

- **Repomix** может упаковать repo в AI-friendly artifact для разового анализа. Источник: https://github.com/yamadashy/repomix
- **DeepWiki-open** и **GitDiagram** могут быстро дать черновую wiki/diagram по GitHub repo, но для AgentFlow рискованны как source of truth: LLM-генерация может сделать ложные claims, пропустить out-of-scope и потребовать модельные ключи или self-host LLM. Источники: https://github.com/AsyncFuncAI/deepwiki-open и https://github.com/ahmedkhaleel2004/gitdiagram

## Таблица Вариантов

Оценка: 1 = слабо, 5 = отлично.

| Вариант | Визуальный результат | Простота внедрения | Анимации | Docs-as-code | Export | Python/TS compatibility | Стоимость | Архитектурное объяснение | Вывод |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **MkDocs Material + Mermaid + D2 + Slidev** | 4 | 5 | 4 | 5 | 4 | 5 | 5 | 5 | **Рекомендованный основной стек** |
| **Structurizr DSL/Lite + MkDocs** | 5 | 3 | 2 | 5 | 5 | 4 | 5 | 5 | Лучший C4 model source-of-truth, но выше learning curve |
| **Docusaurus + MDX + Mermaid/D3** | 5 | 3 | 4 | 5 | 4 | 4 | 5 | 4 | Хорошо, если нужен React-heavy интерактивный сайт; тяжелее для Python-first repo |
| **Slidev standalone** | 4 | 4 | 5 | 4 | 5 | 4 | 5 | 3 | Отлично для demo/talk, недостаточно как полноценный docs-сайт |
| **Reveal.js standalone** | 4 | 3 | 4 | 3 | 4 | 4 | 5 | 3 | Гибко, но больше ручного HTML/CSS/JS, чем Slidev |
| **Motion Canvas / Manim video-first** | 5 | 2 | 5 | 3 | 5 | 4 | 4-5 | 3 | Для одного polished video, не как основной knowledge base |
| **PlantUML/C4-PlantUML + Kroki** | 3 | 3 | 1 | 5 | 4 | 4 | 5 | 4 | Надежно для UML/C4, визуально суше, анимаций почти нет |
| **Observable/D3 custom explorer** | 5 | 1 | 5 | 2 | 3 | 3 | 4-5 | 4 | Максимальная интерактивность, но это отдельная frontend-разработка |

## Рекомендуемая Архитектура Решения

### Основной стек

1. **Content architecture**: Diataxis + arc42.
2. **Architecture notation**: C4 model + ADR.
3. **Docs site**: MkDocs Material.
4. **Диаграммы**:
   - Mermaid для простых sequence/flow/state/API diagrams прямо в Markdown.
   - D2 для главных polished diagrams: data-flow, infra topology, semantic layer map, observability trace map.
   - Structurizr DSL опционально, если нужно сделать C4 model строгим single source of truth.
5. **Интерактивный technical tour**: Slidev deck, лежит в repo и собирается в static web/PDF.
6. **Generated reference**:
   - OpenAPI HTML из `docs/openapi.json` через Swagger UI/Redoc.
   - Python SDK через mkdocstrings.
   - TypeScript SDK через TypeDoc.
   - Terraform через terraform-docs.
   - Helm через helm-docs.

### Почему именно он

- **Минимум миграции**: текущие docs уже Markdown, а проект Python-first.
- **Reproducible и локально**: MkDocs, D2, Slidev, TypeDoc, mkdocstrings запускаются из repo/lockfile/venv/npm scripts.
- **Нулевая обязательная стоимость**: нет обязательного SaaS.
- **Анимации без тяжелого видеопайплайна**: Slidev click animations и D2/Mermaid step diagrams достаточно для data-flow explanation. Motion Canvas можно добавить только для одного video asset, если появится время.
- **Техническая честность**: отдельная страница status/evidence/out-of-scope предотвращает ложные enterprise/compliance claims.
- **Хорошее соответствие AgentFlow**: AgentFlow нужно объяснять как архитектуру, runtime behavior, SDK contract и operations surface, а не как маркетинговый лендинг.

### Запасной минимальный стек

**GitHub Markdown + Mermaid + existing FastAPI Swagger UI + README docs index.**

Что сделать:

- Добавить `docs/explanation/agentflow-tour.md` с Mermaid diagrams.
- Добавить `docs/diagrams/*.mmd`.
- Обновить README ссылкой “Technical walkthrough”.
- Не вводить MkDocs/Slidev до появления времени.

Минус: хуже навигация, нет полноценных интерактивных страниц, слабее визуальный результат.

## Конкретный Deliverable

### Структура файлов

Предлагаемая структура для реализации:

```text
mkdocs.yml
docs/
  index.md
  explain/
    00-what-is-agentflow.md
    01-architecture-overview.md
    02-data-flow.md
    03-components.md
    04-api-and-sdk.md
    05-infra-topologies.md
    06-security-boundaries.md
    07-observability.md
    08-tradeoffs-and-adrs.md
    09-status-and-out-of-scope.md
  diagrams/
    c4-context.mmd
    c4-container.d2
    runtime-entity-lookup.mmd
    runtime-nl-query.mmd
    data-flow-prod.d2
    data-flow-local.d2
    infra-topologies.d2
    observability-trace.d2
  deck/
    slides.md
    package.json
  generated/
    openapi.md или openapi.html
    python-sdk.md
    typescript-sdk/
    terraform.md
    helm.md
```

### Страницы

1. **What is AgentFlow**: real-time data platform for AI agents; what it is not; local demo vs production-shaped architecture.
2. **Architecture Overview**: C4 context + container view.
3. **Data Flow**: ingestion -> processing -> storage -> semantic layer -> FastAPI -> SDK/agents.
4. **Components**: Kafka/Debezium, Flink, Iceberg/DuckDB, Dagster, FastAPI, SDKs, OTel/Prometheus, Docker/Helm/K8s/Terraform.
5. **API and SDK**: public endpoints, Python/TS examples, contract pinning, pagination, streaming events.
6. **Infra Topologies**: local demo, prod-like compose, kind staging, Kubernetes/Helm/Terraform target.
7. **Security Boundaries**: API keys, rate limiting, tenant boundaries, SQL validation, secrets/env config, what is local evidence vs external evidence.
8. **Observability**: metrics, traces, logs, dashboards, failure diagnosis flow.
9. **Tradeoffs and ADRs**: why Kafka/Flink/Iceberg/DuckDB/FastAPI/Dagster, runner-ups, consequences.
10. **Status and Out of Scope**: local quality gates green; external pen-test/AWS OIDC apply/immutable WORM retention not claimed.

### Диаграммы

Нужный минимум:

- C4 Level 1: users/systems around AgentFlow.
- C4 Level 2: containers: ingestion, processing, storage, semantic layer, API, SDKs, observability, infra.
- Runtime sequence: entity lookup from SDK to FastAPI to semantic layer to DuckDB/Iceberg.
- Runtime sequence: NL query explain/execute with SQL guard.
- CDC path: Postgres/MySQL -> Debezium/Kafka Connect -> Kafka -> normalizer -> validation -> Flink/Iceberg.
- Local path: generator -> validate/enrich -> DuckDB/Iceberg -> FastAPI.
- Failure path: bad data -> DLQ -> replay/dismiss -> observability.
- Deployment view: local compose, prod-like compose, kind/Helm, Terraform-managed cloud target.
- Observability trace: request correlation across API/background components.

### Анимации

Достаточно сделать 4 lightweight animations:

1. **Data packet walk**: событие проходит ingestion -> validation -> enrichment -> storage -> semantic -> API -> SDK.
2. **C4 zoom**: context -> container -> runtime sequence.
3. **Failure branch**: bad CDC event уходит в dead letter, затем replay.
4. **Observability path**: один `correlation_id` проходит logs/traces/metrics.

Реализация:

- В Slidev: `v-click`, `v-motion`, slide transitions, step-by-step overlays.
- В MkDocs: статические Mermaid/D2 diagrams + expandable explanations.
- Motion Canvas не брать в Day 1. Добавлять только если нужен MP4 для README/social/demo.

### Команды сборки

Предлагаемый набор после внедрения:

```powershell
# docs site
python -m pip install -e ".[dev]"
python -m pip install mkdocs-material mkdocstrings[python]
mkdocs serve
mkdocs build --strict

# diagrams
d2 docs/diagrams/data-flow-prod.d2 docs/assets/diagrams/data-flow-prod.svg
d2 docs/diagrams/infra-topologies.d2 docs/assets/diagrams/infra-topologies.svg

# Slidev technical tour
cd docs/deck
npm install
npx slidev slides.md
npx slidev export slides.md --format pdf
npx slidev build slides.md --out ../../site/agentflow-tour

# generated reference
npx typedoc --entryPoints ../../sdk-ts/src --out ../generated/typescript-sdk
terraform-docs markdown table infrastructure/terraform > docs/generated/terraform.md
helm-docs --chart-search-root helm
```

Примечание: точные package scripts лучше зафиксировать в отдельном `docs/deck/package.json` или root `Makefile`, чтобы пользователю не помнить длинные команды.

### Интеграция В README/docs/site

- README:
  - добавить “Technical walkthrough” -> `docs/explain/00-what-is-agentflow.md` или MkDocs site URL.
  - добавить “Architecture tour deck” -> `site/agentflow-tour/index.html` после сборки.
  - оставить существующую architecture section, но не превращать README в полный docs-site.
- `docs/architecture.md`:
  - оставить как canonical detailed design или перенести в `docs/explain/01-architecture-overview.md` с минимальными ссылочными правками.
- `site/`:
  - если текущий `site/` - публичный лендинг, не ломать его. MkDocs output можно направить в `site/docs/` или использовать отдельный `mkdocs-site/` в build artifact.
- CI:
  - добавить только docs build gate: `mkdocs build --strict`.
  - не добавлять SaaS-only checks.

## План Реализации На 1-2 Дня

### День 1: Основной docs-site

1. Создать `mkdocs.yml` с Material theme, nav, search, Mermaid config через `pymdownx.superfences`.
2. Создать `docs/explain/` и собрать 8-10 страниц из существующих `README.md`, `docs/architecture.md`, `docs/api-reference.md`, `docs/runbook.md`, `docs/security-audit.md`, `docs/release-readiness.md`.
3. Добавить первые Mermaid diagrams:
   - C4 context.
   - entity lookup sequence.
   - CDC pipeline.
   - failure/DLQ path.
4. Добавить одну D2 polished diagram: `data-flow-prod.d2`.
5. Добавить `docs/explain/09-status-and-out-of-scope.md` с явными disclaimers по external gates.
6. Запустить `mkdocs serve`, визуально проверить navigation/diagrams.
7. Запустить `mkdocs build --strict`.

Acceptance Day 1:

- Static site собирается локально.
- Главные страницы доступны из nav.
- Ни одна страница не заявляет external pen-test, AWS OIDC apply или immutable WORM retention как completed.
- Mermaid/D2 diagrams рендерятся.

### День 2: Интерактивный tour и автогенерация reference

1. Создать `docs/deck/slides.md` на Slidev:
   - opening: “AgentFlow technical walkthrough”
   - data-flow animation
   - C4 zoom
   - runtime entity lookup
   - CDC + DLQ branch
   - API/SDK examples
   - infra topologies
   - security/observability
   - status/out-of-scope
2. Добавить 4 lightweight animations через `v-click`, `v-motion`, transitions.
3. Добавить build/export scripts для Slidev PDF/static.
4. Подключить OpenAPI reference:
   - либо ссылка на FastAPI `/docs` для local runtime,
   - либо static Swagger UI/Redoc artifact из `docs/openapi.json`.
5. Добавить TypeDoc для `sdk-ts/src` и mkdocstrings для Python SDK только если public docstrings достаточно чистые.
6. Добавить README links.
7. Прогнать:
   - `mkdocs build --strict`
   - `npx slidev export docs/deck/slides.md --format pdf`
   - existing test/build gates только если менялись кодовые/SDK/package файлы.

Acceptance Day 2:

- Есть docs site + interactive deck.
- Deck экспортируется в PDF или static HTML.
- API/SDK/infra reference либо сгенерированы, либо явно помечены как future enhancement.
- Status/out-of-scope страница исключает ложные enterprise/compliance claims.

## Что Не Выбирать Сейчас

- **Полный Docusaurus rewrite**: визуально мощно, но для текущего Python/Markdown repo это лишняя миграция.
- **Remotion как обязательная часть**: licensing constraints для компаний и video-first workflow.
- **Lottie-first**: нужен отдельный animation authoring workflow, обычно дизайнерский.
- **DeepWiki/GitDiagram как source of truth**: можно использовать для черновика, но нельзя доверять compliance/status/tradeoff claims.
- **Pure Storybook**: Storybook хорош для UI component docs, а AgentFlow - data platform/API/SDK/infra проект. Источник: https://storybook.js.org/docs/
- **Только auto-generated docs**: API/SDK reference будут полезны, но не объяснят архитектурные решения и границы готовности.

## Финальный Вывод

**Лучшее решение для AgentFlow сейчас: MkDocs Material + Diataxis/arc42/C4 + Mermaid/D2 diagrams + Slidev interactive architecture tour.**

Это дает богатое техническое объяснение проекта, остается бесплатным/open-source, собирается локально, использует уже существующие Markdown-документы, поддерживает интерактивные/анимированные walkthrough без тяжелого видеопроизводства и позволяет честно отделить локально готовое от enterprise/compliance gates, которые пока out of scope из-за бюджета.

