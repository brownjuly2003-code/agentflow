# DV2.0 Multi-Branch — 2-Minute Live Demo Pitch

Спутник к [`demo_evidence.md`](./demo_evidence.md). На каждый блок — что
произносится (≈300 слов всего, ровно 2 минуты речи) и какая команда
исполняется на iMac. SSH-сессия должна быть открыта заранее:

```bash
ssh julia@192.168.1.133
export PATH=$HOME/lima/bin:$HOME/bin:$PATH
```

---

## 00:00 — Хук: бизнес-проблема

> «Mid-market fashion-ритейлер, 50 человек, пять локаций — Москва, Питер,
> Екатеринбург, Дубай, Алматы. Три юрисдикции, шесть систем-источников, и
> один больной KPI — 18% возвратов с маркетплейсов съедают маржу. Пока
> заказы реконсилировались 72 часа, понять *почему* было нельзя. Мы
> построили DV2.0-хранилище, которое сжало этот цикл до 4 часов и дало
> единый источник правды между пятью филиалами. Сейчас покажу его
> бегущим».

(ничего не делать на экране, держать слайд / README open)

## 00:25 — Слой 1: кластер

```bash
kubectl get nodes --show-labels | head -5
```

> «Self-hosted Kubernetes, три ноды. Labels `branch=msk`, `nodepool`,
> `workload` — это не косметика, по ним nodeSelector pinит Postgres на
> один воркер, ClickHouse на другой. В проде те же лейблы становятся
> `branch=dxb`, `branch=ala` — и data sovereignty enforced на уровне
> планировщика, без отдельных кластеров».

## 00:45 — Слой 2: модель

```bash
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT splitByString('_', name)[1] AS kind, count() FROM system.tables
           WHERE database='rv' GROUP BY kind ORDER BY kind"
```

> «Шестьдесят с лишним таблиц: 8 хабов, 8 линков, под сорок сателлитов,
> плюс BV-вьюхи поверх. Сателлиты разрезаны по
> `record_source = {система}__{филиал}` — это load-bearing dimension всей
> архитектуры. Один и тот же `customer_hk` приходит из 1С и из Битрикса,
> но сидит в разных сателлитах — конфликт разрешается через приоритет,
> аудит-след сохраняется».

## 01:05 — Multi-branch proof + latency

```bash
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT splitByString('__', record_source)[2] AS branch, count() AS orders,
           round(count()*100.0/(SELECT count() FROM rv.hub_order),1) AS pct
           FROM rv.hub_order GROUP BY branch ORDER BY pct DESC FORMAT PrettyCompact"
```

> «40/25/15/10/10 — точное распределение, которое X5-loader делает через
> consistent hashing на `store_id`. Это 8 миллионов реальных заказов X5 —
> скан всего hub'а с разбором record_source идёт ~1.1 секунды на 2-vCPU
> kind-кластере на iMac 2017, а serving-запросы ходят в материализованные
> марты за 20-200 ms p99 (см. load-test-baseline.md). Production-движок
> даёт тот же план — мы просто меняем железо».

## 01:25 — Business Vault: MDM

```bash
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --multiline --query "
    SELECT 'msk' AS branch, count() AS rows,
           countIf(first_name != '') AS with_pii,
           countIf(loyalty_segment != '') AS with_loyalty
      FROM rv.bv_customer_mdm__msk
    UNION ALL
    SELECT 'dxb', count(),
           countIf(first_name != ''),
           countIf(loyalty_segment IS NOT NULL AND loyalty_segment != '')
      FROM rv.bv_customer_mdm__dxb
    FORMAT PrettyCompact"
```

> «Business Vault — это views поверх raw vault. PII из 1С, loyalty из
> Битрикса, conflict-resolution через `argMax` по `load_ts`, и `*_source`
> колонки для аудита какая система выиграла. Дубайский view — отдельный
> файл, отдельные satellites; PII никогда не пересекается с МСК».

## 01:50 — Cold tier: anonymized parquet в S3

```bash
kubectl create job --from=cronjob/dv2-cold-offload-msk cold-pitch-$RANDOM -n dv2
sleep 8
kubectl exec -n dv2 minio-0 -- mc ls -r local/cold-tier | tail -5
```

> «Третий слой — anonymized cold tier. CronJob раз в сутки выгружает
> только anon-сателлиты — без PII, без contact data — через `INSERT INTO
> FUNCTION s3(...)` напрямую в MinIO. В проде MinIO заменяется на B2 или
> HF Datasets, манифест не трогаем. 152-ФЗ и закон РК — соблюдены, потому
> что в cold tier по контракту нет персональных».

## 02:00 — Закрытие

> «Всё, что я показал, поднимается одной командой —
> `bash infrastructure/dv2/bootstrap.sh`. Полный список таблиц,
> распределений, query plans и schema лежит в `demo_evidence.md` в
> репозитории. Готова ответить на технические вопросы».

---

## Опциональный Beat 7 — Per-branch CDC fan-out (для Q&A или расширенного демо)

Не входит в 2-минутную версию. Запускать если интервьюер спрашивает
про operational isolation / blast radius / per-branch pause.

```bash
# Pre-state: snapshot обоих CH-DB
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --multiline --query "
    SELECT (SELECT count() FROM oltp_cdc_msk.customers FINAL) AS msk_c,
           (SELECT count() FROM oltp_cdc_msk.orders    FINAL) AS msk_o,
           (SELECT count() FROM oltp_cdc_dxb.customers FINAL) AS dxb_c,
           (SELECT count() FROM oltp_cdc_dxb.orders    FINAL) AS dxb_o"

# Live INSERT в MSK PG database
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops_msk_db <<'SQL'
INSERT INTO customers (customer_id, first_name, last_name, email)
VALUES ('msk-c-DEMO','Demo','User','demo@example.ru')
ON CONFLICT (customer_id) DO NOTHING;
SQL

# 8s WAL roundtrip → CH видит row
sleep 8
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT * FROM oltp_cdc_msk.customers FINAL WHERE customer_id='msk-c-DEMO' FORMAT Vertical"

# Изоляция: DXB CH-DB не видит MSK row
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT count() AS cross_leak FROM oltp_cdc_dxb.customers WHERE customer_id LIKE 'msk-%'"
```

> «Сессия 4 поставила один CH-DB поверх обоих филиалов через
> `schema_list` — нормально для unified-analytics, но недостаточно для
> operational pause. Сессия 5 разнесла источник: `ops_msk_db` и
> `ops_dxb_db` — отдельные Postgres-БД, каждая мапится в свой
> CH-MaterializedPostgreSQL. Auto-named publication
> `<src>_ch_publication` больше не коллидирует. PeerDB OSS был
> архитектурно чище, но Temporal + flow-services не поместились на
> 8GB iMac — per-DB split даёт тот же property нативно. INSERT в MSK
> доезжает за 8 секунд, DXB не видит. Production-pattern будет тот же,
> только под управлением PeerDB или Debezium».

После Beat 7 — `DELETE FROM ops_msk_db.customers WHERE customer_id='msk-c-DEMO'`
для cleanup перед следующим прогоном.

---

## Подготовка перед запуском

1. ssh + `kubectl get nodes` — убедиться что 3 ноды Ready
2. `kubectl get pods -n dv2` — clickhouse-0, postgres-0, minio-0 Running
3. Заранее открыть в редакторе: `docs/dv2-multi-branch/architecture.md`
   (на случай вопроса «покажи pipeline») и `warehouse/agentflow/dv2/spec.yaml`
   (на случай вопроса «как добавить новый источник»)
4. Тайминг ёмкий — речь даёт 2:00 ровно при умеренном темпе, команды
   исполняются параллельно

## Fallback (если кластер недоступен)

Заменить live-запуски на скриншоты блоков 1–6 из `demo_evidence.md`,
остальное произносится как есть. Время не меняется.
