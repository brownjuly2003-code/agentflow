# Ревью: интерактивное техническое описание AgentFlow

> Контекст: анализ проведён только по предоставленному описанию. Содержимое репозитория не изучалось.

---

## 1. Вердикт: simplify

Предложенный инструментарий (MkDocs Material + Mermaid + Slidev) — хороший выбор. Переусложнение возникает не в инструментах, а в методологиях: **Diataxis + arc42 + C4 одновременно — избыточно для Day 1**. Нужно выбрать один каркас и дополнить его интерактивностью, а не документологией.

---

## 2. Замечания по плану

### 2.1. Переусложнён ли стек?

**Инструменты — нет.** MkDocs Material + Mermaid/D2 + Slidev — это ровно то, что нужно для 0-бюджетного проекта.

**Методологии — да.** Три frameworks одновременно создадут friction:
- **Diataxis** хорош для обучающего контента (tutorials / how-to / reference / explanation).
- **arc42** создан для enterprise architecture и требует ~12 разделов. Для open-source data platform это тяжеловато.
- **C4** нужен, но достаточно Level 1–2. Level 3–4 отнимают время и быстро устаревают.

**Рекомендация:** взять **Diataxis как скелет** (читатель сразу понимает, tutorial это или reference), внутри него использовать **C4 Level 1–2** для архитектуры, а arc42 — отложить до появления enterprise-клиентов.

### 2.2. Что убрать из Day 1

1. **arc42** — не нужен на старте. Дублирует Diataxis + C4.
2. **D2** — если в команде нет уже настроенного CI с D2-binary, начинайте с **Mermaid**. D2 красив, но добавляет dependency. Вернуть, когда диаграммы станут читаемее.
3. **C4 Level 3–4** (компоненты / код). В Day 1 достаточно Level 1 (System Context) и Level 2 (Container).
4. **Автогенерация диаграмм из исходников** — пустая трата времени. Лучше руками нарисовать 4 актуальные схемы, чем поддерживать парсер.
5. **External pen-test / compliance / WORM / Object Lock** — явно исключены из Day 1 по условию.
6. **Попытка покрыть весь ADR-каталог** в интерактивном описании. ADR остаются в `docs/decisions/`, в walkthrough попадают только итоговые решения.

### 2.3. Чего не хватает для хорошего технического walkthrough

1. **Runnable Quick Start** — единая страница `docker compose up && curl /v1/health`. Без этого всё остальное — теория.
2. **Live API Explorer** — встроенный Swagger UI или хотя бы copy-paste ready `curl` / Python / TypeScript блоки рядом с каждым endpoint.
3. **SDK Quickstart с реальным вызовом** — не просто "установите пакет", а "вот 5 строк кода, которые возвращают данные".
4. **Troubleshooting / FAQ** — что делать, если Kafka не поднялась, Flink job падает, DuckDB медленный.
5. **Performance / SLO в человекочитаемом виде** — таблица latency (p50/p99), throughput, а не ссылка на Prometheus.
6. **Changelog и Migration Guide** — даже если версия одна, заглушка с versioning policy важна.
7. **One-page Cheat Sheet** — архитектура, стек, порты, переменные окружения на одной странице A4-style.

### 2.4. MkDocs Material + Mermaid/D2 + Slidev vs альтернативы

| Критерий | MkDocs Material | Docusaurus | VitePress | GitBook / ReadMe |
|---|---|---|---|---|
| Бюджет 0 | ✅ | ✅ | ✅ | ❌ SaaS |
| Техническая навигация | ✅ Отлично | Хорошо | Хорошо | Средне |
| Встроенный поиск | ✅ | Нужен Algolia | Нужен Algolia | ✅ |
| Mermaid из коробки | ✅ Плагин | ✅ Плагин | ✅ Плагин | Частично |
| Code blocks / copy | ✅ | ✅ | ✅ | ✅ |
| Slidev-интеграция | Через iframe / ссылку | Аналогично | Аналогично | Нет |

**Вывод:** MkDocs Material — оптимален. Docusaurus имеет смысл, если планируется маркетинговый сайт + docs в одном флаконе. Slidev лучше Reveal.js для tech talks, потому что Markdown-first, Vue-based и легко деплоить на Vercel/Netlify.

---

## 3. Финальная рекомендуемая структура

### Документация (MkDocs Material): 8–10 страниц

Структура следует Diataxis: сверху Tutorial/Reference, сбоку Explanation/How-To.

```
docs/
├── index.md                    # 1. Overview: что это, зачем, стек, 3-секундный pitch
├── quickstart.md               # 2. Tutorial: docker compose up → первый запрос (15 мин)
├── architecture/
│   ├── index.md                # 3. C4 Level 1 + Level 2 + Data Flow (Mermaid)
│   └── decisions.md            # Ключевые trade-offs (не все ADR, а 3–5 главных)
├── concepts.md                 # 4. Explanation: streaming-first, semantic layer, quality gates
├── components.md               # 5. Reference: Kafka/Flink/Iceberg/DuckDB/Agent API (таблица + схема)
├── api/
│   └── index.md                # 6. API Reference + runnable examples (curl/Python/TS)
├── sdk.md                      # 7. SDK Quickstart: install → код → результат
├── deployment.md               # 8. How-To: local (Compose) → prod (Helm/K8s overview)
├── observability.md            # 9. Metrics, OpenTelemetry, SLOs, alerts (честные цифры)
└── contributing.md             # 10. Troubleshooting, FAQ, как поднять dev env
```

**Почему именно так:**
- `index.md` — landing. Без него поисковики и GitHub теряют контекст.
- `quickstart.md` — главная страница для конверсии. Если пользователь не поднял стек за 15 минут, он уйдёт.
- `architecture/` — C4 L1–L2 хватает. Больше диаграмм = больше лжи (дрейф от кода).
- `concepts.md` отдельно от `architecture.md`, потому что "почему streaming-first" и "как выглядит система" — разные ментальные модели.
- `api/` + `sdk.md` — разделены, потому что REST reference и "как писать клиент" — разные аудитории.
- `observability.md` вынесен отдельно, чтобы честно показать, что замеряется и какие лимиты есть.

### Slidev Deck: 12–18 слайдов

```
01. Title + Tagline (AgentFlow: real-time data for AI agents)
02. Problem: why dashboards fail agents
03. Solution in 1 sentence
04. Architecture Overview (C4 L1 — Mermaid SVG)
05. Data Flow (Kafka → Flink → Iceberg → API) — анимированная стрелка
06. Key Design Principles (5 bullets, 1 icon each)
07. Live Demo — docker compose up (asciinema или terminal-recording)
08. API + SDK (3-pane: curl / Python / TypeScript с реальным JSON)
09. Quality Gates (schema + semantic validation — до/после)
10. Observability (Grafana screenshot или Mermaid-диаграмма метрик)
11. Deployment: Local vs Production (2 колонки)
12. Performance (честные цифры: p50 ~220ms, оговорки)
13. Trade-offs (честно: зачем DuckDB по умолчанию, когда ClickHouse опционален)
14. Roadmap (3 ближайших milestone, без дат, если нет уверенности)
15. Links + GitHub + Docs QR
```

**Дополнительные слайды (при необходимости):**
- 16. Security Model (не "SOC2", а "defense-in-depth: mTLS, validation, DLQ")
- 17. Benchmark Methodology (как замеряли, на каком железе)
- 18. Community / Contributing (как прислать PR)

---

## 4. Риски ложных claims и честные формулировки

| Ложный claim (не используй) | Честная формулировка |
|---|---|
| "Enterprise-ready" | "Core platform runs in containerized environments. Enterprise hardening (SSO, RBAC, audit logs) is on the roadmap." |
| "SOC 2 / ISO 27001 compliant" | "Security model follows defense-in-depth principles. Formal compliance certifications are not yet obtained." |
| "AWS OIDC Terraform apply is production-ready" | "Terraform modules are provided as reference architecture. Production IAM policies must be reviewed by your cloud security team." |
| "Guaranteed sub-second latency" | "p50 latency is ~220ms in local benchmarks. Actual latency depends on infrastructure, data volume, and network conditions." |
| "WORM / immutable retention enabled" | "Iceberg supports time-travel and snapshot isolation. WORM object-lock policies are not configured by default." |
| "Pen-tested by external vendor" | "Security guidelines are documented. External penetration testing is planned for a future release." |
| "Zero data loss guarantee" | "Dead letter topic captures failed events for replay. Durability guarantees depend on Kafka and storage replication settings." |
| "Auto-scales to any load" | "Helm charts include HPA templates. Auto-scaling behavior must be tuned to your cluster and workload." |

**Правило:** если функция требует настройки пользователя или не протестирована end-to-end в CI — это не "ready", это "supported with configuration required".

---

## 5. Итоговый action plan

1. **Создать ветку `docs/interactive-walkthrough`.**
2. **Инициализировать MkDocs Material** с темой `slate`, включить плагин `search`, `minify`, `mermaid2`.
3. **Написать 3 приоритетные страницы:** `index.md`, `quickstart.md`, `architecture/index.md`.
4. **В quickstart встроить проверку:** `docker compose ps` + `curl http://localhost:8000/v1/health` должны работать.
5. **Создать Slidev deck** из 15 слайдов, деплой на GitHub Pages / Vercel.
6. **Провести self-check:** прочитать каждый claim из раздела 4 и заменить на честную формулировку.
7. **Не добавлять arc42, D2, C4 L3–4 до запроса от пользователей.**
