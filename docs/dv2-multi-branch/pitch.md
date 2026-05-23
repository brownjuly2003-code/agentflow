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

> «38 таблиц: 8 хабов, 8 линков, 22 сателлита. Сателлиты разрезаны по
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
> consistent hashing на `store_id`. Запрос — 3 миллисекунды на 10K строк
> в kind-кластере на iMac 2017. Production-движок даёт тот же план — мы
> просто меняем железо».

## 01:25 — Business Vault: MDM

```bash
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT branch, count() rows, countIf(first_name != '') with_pii,
                  countIf(loyalty_tier != '') with_loyalty
           FROM (SELECT 'msk' branch, * FROM rv.bv_customer_mdm__msk UNION ALL
                 SELECT 'dxb', * FROM rv.bv_customer_mdm__dxb) GROUP BY branch FORMAT PrettyCompact"
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
