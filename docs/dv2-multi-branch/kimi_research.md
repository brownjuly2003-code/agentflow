Исследование завершено. Готовлю финальный отчёт.

---

=== REAL CASE STUDIES (PRIMARY) ===

**1. Qlever — DWH для fashion e-commerce на маркетплейсах (РФ)**
URL: https://habr.com/ru/articles/837578/
Релевантность: Прямой аналог профиля — fashion e-com, интеграция 1С + Wildberries + OZON + MPStats через REST API и SFTP. Реализована многоуровневая архитектура LSA (Staging → Core → DDS → Data Mart) на ClickHouse + DBT + Dagster. Решена проблема дедупликации 25 000 SKU и разнородности возвратов между WB/Ozon.
Цитата для собеса: «В ходе реализации проекта выяснилось, что на WB возврат возможен без совершения транзакций, а на OZON только после проведения транзакции. Вопрос разнородности показателей удалось решить сравнением количества продаж и транзакций и приведением данных к единым структурам и ключам на Core Layer DWH. Наглядное представление информации помогло устранить до 80% ошибок при планировании отгрузок».

**2. «Магнит OMNI» — хранилище данных крупнейшего ритейлера РФ**
URL: https://habr.com/ru/companies/magnit/articles/864472/ и https://habr.com/ru/companies/magnit/articles/955312/
Релевантность: Архитектура retail + e-commerce + маркетплейс + loyalty. Data Vault 2.0 строится в Greenplum (batch, «сегодня за вчера»), ClickHouse используется для real-time BI-нагрузки и журналов мобильного приложения. Интеграция — Kafka + Debezium (CDC), оркестрация — Airflow + DBT.
Цитата для собеса: «Greenplum. Ядро хранилища. Здесь мы строим Data Vault, рассчитываем метрики в режиме «сегодня за вчера»… ClickHouse используем для аналитики в реальном времени, BI-нагрузки… Kafka + Debezium — основной метод интеграции данных в хранилище».

**3. ClickHouse Internal DWH — гибридная архитектура SaaS-компании**
URL: https://clickhouse.com/blog/building-a-data-warehouse-with-clickhouse (Part 1 и Part 2)
Релевантность: 10+ источников (AWS, GCP, Salesforce, Segment, Marketo, самописные API), multi-cloud ingestion, Docker-контейнеры, S3 как staging, Airflow + dbt. Команда из 3 человек обслуживает ~200 GB RAM в ClickHouse Cloud + 8 EC2 при cost ~$1,500/мес. Доказали, что двухслойная архитектура (raw → mart) не работает для 5+ источников, и ввели DDS (Detail Data Store).
Цитата для собеса: «The idea of having only two logical layers, unfortunately, doesn't work. We found that for calculating really complex metrics that can be backfilled and that need data from 5+ data sources, we have to create dependencies between different marts… we researched competitors pricing and performance and believe that another cloud analytical database would be much more expensive in our case».

**4. Строительный холдинг — Data Lakehouse с 15 базами 1С**
URL: https://habr.com/ru/articles/931282/
Релевантность: Greenfield-проект, 15 баз 1С (ЗУП, бухгалтерия, КА) интегрированы через Kafka с schema registry. Слои: Iceberg/MinIO S3 → Trino → ClickHouse (витрины). ~1000 моделей DBT. Kubernetes + ArgoCD + Harbor для CI/CD.
Цитата для собеса: «Для интеграции всех баз 1С используется Apache Kafka, обеспечивая удобный, легко масштабируемый процесс… Все сервисы развернуты в кластере Kubernetes… слой витрин выгружается в ClickHouse, который является единой точкой доступа к данным».

**5. PeerDB — production CDC из Postgres в ClickHouse**
URL: https://clickhouse.com/blog/enhancing-postgres-to-clickhouse-replication-using-peerdb и https://www.cloudraft.io/blog/postgres-to-clickhouse-replication
Релевантность: Прямое подтверждение паттерна Postgres (OLTP hot) → ClickHouse (OLAP warm). Логическая репликация, latency ~10 секунд, S3 staging для resilience (репликация не ломается при даунтайме ClickHouse). Обработка billions of rows и terabytes данных в реальном времени.
Цитата для собеса: «PeerDB team had the opportunity to work with multiple ClickHouse customers, helping them replicate billions of rows and terabytes of data from Postgres to ClickHouse… Flushing the changes to the internal stage ensures the replication slot is consumed even when the target is down».

**6. Mid-sized e-commerce — миграция с Redshift на ClickHouse**
URL: https://dev.to/johalputt/how-to-build-a-real-time-analytics-dashboard-with-clickhouse-24-and-superset-30-2474
Релевантность: Mid-market e-com, миграция с managed Redshift + Tableau на self-hosted ClickHouse 24.3 + Superset. TCO снижен с $68k/мес до $12k/мес. Kafka → ClickHouse native engine, materialized views для 1-min агрегаций.
Цитата для собеса: «Migrated to ClickHouse 24.3 on 3-node cluster… p99 latency dropped to 98ms, throughput increased to 58k events/sec, TCO reduced to $12k/month — saved $672k/year».

**7. K3s в retail edge — отраслевой production-паттерн**
URL: https://www.suse.com/c/k3s-and-k8s-key-differences-and-use-cases-explained/ и https://reintech.io/blog/k3s-tutorial-lightweight-kubernetes-edge-iot
Релевантность: K3s как CNCF-certified lightweight Kubernetes для retail-локаций: POS, локальная аналитика, inventory management на Intel NUC с 4GB RAM. Подтверждает обоснование self-hosted k3s вместо managed k8s для edge-филиалов.
Цитата для собеса: «I've deployed K3s on retail store edge servers running on Intel NUCs with just 4GB RAM, managing point-of-sale systems, local analytics, and inventory management applications simultaneously».

**8. ClickHouse Cloud UAE — подтверждение relevance ОАЭ региона**
URL: https://clickhouse.com/blog/clickhouse-cloud-azure-uae-north
Релевантность: ClickHouse выделяет e-commerce & retail как primary use-case для UAE региона, упоминая compliance и real-time inventory. Подтверждает, что выбор ClickHouse + облачный cold tier консистентен с региональной стратегией.
Цитата для собеса: «E-Commerce & Retail: With the Middle East's e-commerce sector booming, retailers need to analyze customer behavior, inventory levels, and market trends instantaneously. ClickHouse's columnar architecture makes it possible to run complex analytical queries across petabytes of data».

**Частичные совпадения / не найдено:**
- Не нашёл публичного named customer case со всеми признаками: Data Vault 2.0 ПРЯМО в ClickHouse как primary DWH (Магнит строит DV в Greenplum, ClickHouse — слой витрин).
- Не нашёл публичного кейса с k3s self-hosted ИМЕННО для data engineering workloads в named customer посте (есть retail edge, но не DE-specific).
- Не нашёл публичного кейса с multi-jurisdiction архитектурой РФ + ОАЭ + Казахстан в одном named customer описании (есть аналитика compliance framework по отдельности).

---

=== POLISHED LEGEND (SECONDARY) ===

«Мы строили DWH для mid-market fashion-ритейлера, 50 человек, пять точек присутствия — Москва, СПб, Екатеринбург, Дубай, Алматы. Ключевой бизнес-драйнер: 18% возвратов с маркетплейсов, из-за которых съедалась маржа. Без единого хранилища невозможно было понять, связан ли возврат с рассинхронизацией остатков между WB и Ozon, поэтому появилось требование SCD2 на цены и stock. Вторая боль: логистика в Excel давала 72-часовой лаг на реконсиляцию заказов, а 1С и Битрикс24 жили в разных временных зонах.

Архитектура фиксирована тремя ярусами: Postgres on-prem — hot OLTP, 1 месяц; ClickHouse on-prem — Data Vault 2.0, warm 1 год для BI; cloud cold — anonymized Parquet в S3-compatible, on-demand для стратегических сессий. Compute — self-hosted k3s: три ноды в HQ, по одной edge-ноде в каждом филиале. Modeling — DV2.0 с record_source = {system}__{branch_code} и hash-keys для параллельной загрузки hub/link/satellite без sequential dependencies.

Результаты за 8 месяцев: реконсиляция заказов сократилась с 72 до 4 часов, инциденты двойных продаж одного SKU упали на 91%, TCO BI-инфраструктуры — $1,800 в месяц против оценочных $12k за managed аналог. Edge-ноды k3s позволили запускать data quality checks локально, не пропуская сырые PDI через границу. Сейчас AI-агент работает как anomaly detection на satellite цен — ловит dump конкурентов за 15 минут вместо двух дней ручного анализа».

---

=== PUSHBACK PREPARATION (TERTIARY) ===

**Q1: Почему DV2.0, а не data mesh / data fabric / Anchor modeling?**
A1: Data mesh требует зрелых product-oriented команд в каждом домене — у компании в 50 человек нет ресурсов на пять data-product ownerов. DV2.0 даёт ту же гибкость интеграции новых источников (мы добавили Excel-логистику за три дня), но силами одной команды. Data fabric — vendor-heavy концепт без зрелых open-source implementation под наш стек Postgres+ClickHouse+k3s. Anchor modeling слишком гранулярен для mid-market: 80K SKU и 70K клиентов — не тот масштаб, где выигрыш от anchor-разложения перекрывает операционные издержки.

**Q2: Почему ClickHouse, а не Apache Pinot / Druid / StarRocks?**
A2: StarRocks силён в многотабличных JOIN, но в DV2.0 узкие satellites — паттерн point lookups + wide scans, где ClickHouse historically unbeatable. Druid/ Pinot заточены под event-streaming с pre-aggregation, а у нас 60% данных — batch из 1С и Excel. ClickHouse даёт 10x compression на наших string-heavy satellites и нативный Postgres CDC через PeerDB с latency ~10 секунд, что критично для операционной аналитики возвратов.

**Q3: Почему k3s self-hosted, а не managed Yandex Managed Kubernetes / EKS / GKE?**
A3: Пять юрисдикций — пять разных compliance-режимов. Managed Kubernetes в РФ требует сертификации средств защиты информации по 152-ФЗ, что добавляет 6+ месяцев на каждый регион. k3s — single binary, CNCF-certified, мы реплицируем одну конфигурацию во все филиалы через ArgoCD. Cost: $0 license против $800–1,200/мес за managed control plane в каждом регионе. На edge-нодах k3s работает на 4GB RAM, что недостижимо для managed k8s.

**Q4: Почему cold tier в облаке, а не on-prem object storage (MinIO/Ceph)?**
A4: On-prem object storage требует отдельной команды для maintenance, 3-2-1 backup и replacement дисков в разных странах. Cloud cold — Backblaze B2 / HF Datasets с $6/TB, immutable, с географической избыточностью. Для anonymized данных это приемлемо по 152-ФЗ и ЗоПД РК, так как в cold tier нет ПДн — только агрегаты и обезличенные parquet. Если завтра закроют один из филиалов, данные останутся доступны без шиппинга железа.

**Q5: Почему Postgres как hot OLTP, а не CockroachDB / YugabyteDB для multi-region?**
A5: CockroachDB требует minimum 5 нод для production и имеет write amplification, который на нашем объёме (1–2K заказов/день) даст 3x дисковой нагрузки без реального выигрыша. Мы не строим глобально-консистентный OLTP: в каждом филиале своя regional Postgres instance с nightly reconcile через DV2.0 hub. Logical replication + PeerDB даёт latency 10s в ClickHouse — этого достаточно для аналитики. Cost five-node Cockroach vs single-node Postgres per region говорит сам за себя.

**Q6: Как обеспечивается single source of truth между пятью локациями?**
A6: DV2.0 hub выступает единым якорем: hash-key от business key (SKU, client_email) детерминистический, поэтому один и тот же клиент из Битрикс24 и 1С получает один hub_customer_hk. Satellites split по record_source = {system}__{branch_code}, что сохраняет аудитпрослеживаемость. Конфликты разрешаются через satellite priority: 1С — master для цен и остатков, Битрикс — для контактов и статусов лидов. Business vault — единая витрина с soft rules, куда стекаются все ветки.

**Q7: Что с CDC из 1С — там же deltas плохо exposed?**
A7: Мы используем гибрид: для объектов с подписками — план обмена 1С + Kafka Rest (паттерн доказан в строительном холдинге с 15 базами 1С). Для legacy-справочников без событий — hourly XML dump по SFTP с последующим hash-diff в staging. Мы не ждём идеального CDC: 80% данных идёт почти real-time через события, 20% — batch reconcile с приемлемым 1-часовым лагом. Главное — idempotency и deterministic hash-keys, чтобы повторная загрузка не портила vault.

**Q8: Как обосновать overhead трёхслойной DV2.0 для mid-market, а не просто star schema в ClickHouse?**
A8: Это не overhead, а investment в скорость onboarding новых источников. Добавление нового маркетплейса (например, Яндекс.Маркет) в DV2.0 — два спринта: новый source → staging → satellite к существующему hub. В Kimball — переделка fact table, всех агрегатов и downstream dashboards. В кейсе Qlever аналогичный fashion-retail показал: unified core layer позволил сравнивать WB и Ozon в одних ключах через 3 месяца после старта. Мы повторили этот паттерн.
