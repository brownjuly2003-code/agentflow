# Задача для исследовательской модели

Контекст: data-инженер готовит portfolio-кейс для собеса (mid/senior DA/DE уровень, РФ + СНГ). Архитектура УЖЕ зафиксирована (не предлагать альтернативы — только усиливать).

## Сценарий (синтетический, готовый — нужен для понимания контекста)

**Бизнес:** mid-market e-com одежды/обуви, РФ-ритейлер. ~50 сотрудников, multi-channel (свой сайт + физические шоу-румы + маркетплейсы ВБ/Озон). ~1000-2000 заказов/день, ~80К SKU после дедупликации, ~70К активных клиентов.

**Источники-каша:** 1С (учёт/склад) + Битрикс24 (CRM) + Excel-логистика + кастомный XML-обмен с сайтом + API-интеграции маркетплейсов.

**5 локаций / 3 юрисдикции:** Москва (HQ), Санкт-Петербург, Екатеринбург, Дубай (ОАЭ), Алматы (Казахстан). Per-jurisdiction data sovereignty (152-ФЗ для РФ, PDPL для ОАЭ, ЗоПД для РК).

**Архитектура (зафиксирована):**
- 3 storage-tier: Postgres on-prem (OLTP, hot 1 мес) → ClickHouse on-prem (DV2.0, warm 1 год BI) → Cloud cold (anonymized parquet, on-demand для стратегических сессий)
- Compute: self-hosted k3s, 3 ноды в HQ + по 1 edge-ноде в каждом филиале
- Modeling: Data Vault 2.0, record_source = `{source_system}__{branch_code}`
- Cloud cold: S3-compatible (HF Datasets / Backblaze B2), anonymization-first

## ГЛАВНАЯ задача

**Найти РЕАЛЬНЫЕ публично описанные кейсы**, максимально близкие к этому профилю. Что годится:
- Blog-посты компаний (engineering blogs, habr.com, medium.com, dev.to)
- Conference talks (Highload++, Datafest, dbt Coalesce, Data+AI Summit, ClickHouse Meetup, PG Day, FOSDEM, KubeCon)
- GitHub-репозитории с README, описывающим production architecture
- Whitepaper-ы вендоров (ClickHouse, Snowflake, Databricks) с named customer references
- Open-source case study books, dataengineering.wiki, dbt case studies

Критерии релевантности (по убыванию важности):
1. Mid-market retail / e-com / multi-channel
2. Multi-source integration с legacy ERP (1С, SAP, MS Dynamics, NAV)
3. Data Vault 2.0 в реальной production (особенно с ClickHouse / Postgres / Snowflake)
4. Hybrid on-prem + cloud architecture с обоснованием cost-driven trade-off
5. Self-hosted k3s/k8s для DE workloads (НЕ managed)
6. Multi-jurisdiction compliance (РФ + СНГ / ЕАЭС / Ближний Восток / ОАЭ / Казахстан)

Минимум 5 кейсов, оптимум 10. Для каждого:
- Title
- URL (рабочий, не выдуманный)
- 2-3 предложения о том, что в этом кейсе релевантно нашему сценарию
- Что можно прямо процитировать на собесе как «вот такие компании делают похоже»

## SECONDARY задача (если real cases не покрывают всё)

**Отполировать синтетическую legend** до максимальной убедительности:
- Найти слабые места и закрыть их
- Добавить конкретные бизнес-KPI, driving каждое архитектурное решение (например: «возвраты с маркетплейсов 18% — это вылилось в требование SCD на цены и складские остатки»)
- Без 2026-аномалий, современно (упомянуть AI-агентов уместно, не для галочки)
- 200-300 слов, готовый 2-min behavioral pitch на собесе

## TERTIARY: подготовка к pushback

5-8 вопросов senior-интервьюера по слабым местам + готовые ответы. Примеры:
- «Почему DV2.0, а не data mesh / data fabric / Anchor modeling?»
- «Почему ClickHouse, а не Apache Pinot / Druid / StarRocks?»
- «Почему k3s self-hosted, а не managed EKS / GKE / Yandex Managed K8s?»
- «Почему cold tier в облаке, а не on-prem object storage (MinIO/Ceph)?»
- «Postgres как hot OLTP — почему не CockroachDB / YugabyteDB для multi-region?»
- «Как обеспечивается single-source-of-truth между 5 локациями?»
- «Что с CDC из 1С — там же deltas плохо exposed?»

## Формат вывода

```
=== REAL CASE STUDIES (PRIMARY) ===
1. [Title]
   URL: ...
   Релевантность: ...
   Цитата для собеса: ...
2. ...

=== POLISHED LEGEND (SECONDARY) ===
[200-300 слов pitch]

=== PUSHBACK PREPARATION (TERTIARY) ===
Q1: ...
A1: ...
...
```

На русском. Цитаты/названия — на языке источника. Если кейс не нашёлся — честно: «не нашёл публичного кейса со всеми признаками; ближайшие частичные совпадения: ...». Не выдумывай и не галлюцинируй URLs.
