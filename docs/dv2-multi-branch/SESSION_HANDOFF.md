# DV2.0 Multi-Branch — Session Handoff (2026-05-23)

Working snapshot после двух сессий. Ветка `feat/dv2-multi-branch`.

> **Session 2 (2026-05-23 morning)** — закрыто: k8s manifests вынесены в
> `infrastructure/dv2/`, end-to-end dataflow diagram (`architecture.md`),
> live demo evidence (`demo_evidence.md`), main README обновлён,
> MD5/unhex gotcha задокументирован. Кластер `hq-demo` остался работать.

## Что сделано

### 1. Архитектурная легенда (Tasks #1 + #2)
- **Домен:** mid-market e-com одежды/обуви, 5 локаций (МСК HQ + СПб + Екб + Дубай + Алматы), 3 юрисдикции (РФ + ОАЭ + РК)
- **Источники:** 1С + Битрикс24 + Excel-логистика + XML-обмен сайта + ВБ/Озон API
- **Архитектура:** 3-tier storage (Postgres hot 1мес → ClickHouse DV2.0 warm 1год → cloud cold anonymized parquet)
- **Compute:** self-hosted upstream Kubernetes, 3 ноды HQ + 1 edge на филиал
- **Modeling:** Data Vault 2.0 с `record_source = {source_system}__{branch_code}` как load-bearing dimension
- **Compliance:** per-branch data sovereignty, anonymization-first для cloud cold tier

### 2. Исследование реальных кейсов
- Найдено 8 публично описанных production-аналогов: **Магнит OMNI** (DV2.0 в Greenplum + ClickHouse), **X5 Retail Hero** (45.8М реальных транзакций на Kaggle), **Лента BigTarget**, ClickHouse internal DWH, стройхолдинг с 15×1С, PeerDB Postgres→ClickHouse CDC, k3s retail edge, ClickHouse UAE
- Сохранено в `kimi_research.md` (общие кейсы), `kimi_magnit_research.md` (специфика российских ритейлеров)

### 3. DV2.0 модель (Task #2)
- Schema design: `schema_dv2.md` — 8 хабов, 8 линков, satellite-стратегия per-source × per-branch, ClickHouse DDL, anonymization layer, loading order, X5 data binding
- DDL files: `warehouse/agentflow/dv2/raw_vault/` — 8 хабов, 8 линков, 22 сателлита (реалистичная матрица), все ClickHouse 25.x syntax с idempotent `IF NOT EXISTS`
- Generator: `generate_satellites.py` + `spec.yaml` + `satellites_template.sql.j2` для масштабирования
- Bootstrap: `__init.sql` + `README.md`

### 4. X5 Retail Hero loader
- `warehouse/agentflow/dv2/loaders/x5_retail_hero/` — 7 файлов ~750 строк Python
- CLI: `python loader.py --csv-dir <X5> --clickhouse-host <h> --batch-size 100000`
- Branch distribution: 40/25/15/10/10 (msk/spb/ekb/dxb/ala) через consistent hashing на store_id
- Использует `hashlib.md5().digest()` (правильный 16-byte raw, без unhex)

### 5. Демо-инфраструктура развёрнута (Task #4)
- **iMac (2017, Intel i5, 8GB, macOS 13.7.8)** при 192.168.1.133 — full self-hosted demo host
- **Lima 2.1.1** VM (Ubuntu 24.04 на Apple VZ, без QEMU) → провайдит Docker daemon на маке
- **kind 0.31.0 → upstream Kubernetes 1.35.0** — 3-node кластер `hq-demo`:
  - `hq-demo-control-plane` (nodepool=hq-control, branch=msk)
  - `hq-demo-worker` (workload=postgres, nodepool=hq-data-tier-a)
  - `hq-demo-worker2` (workload=clickhouse, nodepool=hq-data-tier-b)
- **dv2 namespace** с deployment manifests:
  - **ClickHouse 25.5** StatefulSet pinned на worker2 через `nodeSelector: workload=clickhouse`, 5Gi PV
  - **Postgres 17-alpine** StatefulSet pinned на worker через `nodeSelector: workload=postgres`, 2Gi PV
  - Secret `ch-creds` с credentials default/demo
- **38 DV2.0 таблиц** созданы в БД `rv` (8 hubs ReplacingMergeTree + 8 links ReplacingMergeTree + 22 satellites MergeTree partitioned by toYYYYMM)
- **Синтетические данные**: 6 stores / 2000 customers / 800 products / 10000 orders / 10000 order-customer links / 10000 order-store links / 24938 line items
- **BI-валидация**: multi-branch распределение точно 40/25/15/10/10 по `record_source`, query latency 2ms на count() 25K строк

## Состояние кластера (на 2026-05-23 ~07:40 MSK)

Все компоненты бегут. Кластер выживет:
- Перезагрузку iMac (lima auto-start не настроен; нужно `limactl start docker` после reboot)
- Закрытие ssh-сессии (caffeinate активен до 2026-05-23 ~00:35 MSK = +4h от старта)
- Сетевые блипы (kind+colima переживают)

## Как возобновить (новая сессия)

### Если iMac жив и кластер бежит
```bash
# с Windows-машины:
ssh julia@192.168.1.133 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH && kubectl get nodes && kubectl get pods -n dv2'
```
Если возвращает 3 Ready ноды + 2 Running pods — все нормально.

### Если iMac перезагружался
```bash
ssh julia@192.168.1.133 '
  export PATH=$HOME/lima/bin:$HOME/bin:$PATH
  nohup caffeinate -dimsu -t 14400 >/tmp/caffeinate.log 2>&1 & disown
  limactl start docker
  # kind кластер автоматически восстановится из Docker volumes
  kubectl get nodes
'
```

### Если кластер потерян / нужно пересоздать с нуля
- Все шаги в этом файле; ключевые артефакты:
  - SSH key: `~/.ssh/id_ed25519` на Windows, public установлен в `julia@192.168.1.133:~/.ssh/authorized_keys`
  - DDL: `warehouse/agentflow/dv2/__init.sql` + `raw_vault/{hubs,links,satellites}/*.sql`
  - Seed: `warehouse/agentflow/dv2/synthetic_seed.sql`
  - K8s manifests: ✅ committed в `infrastructure/dv2/` — `bash infrastructure/dv2/bootstrap.sh` пересобирает кластер с нуля и накатывает DDL + seed (idempotent).

## Что осталось

### Task #3 — End-to-end data flow diagram ✅ DONE (session 2)
- `docs/dv2-multi-branch/architecture.md` — Mermaid диаграмма: 1С / Битрикс / WMS / Excel / XML / WB+Ozon → Postgres OLTP → PeerDB CDC → ClickHouse DV2.0 (raw → business → mart) → anonymized parquet S3
- Включает per-stage contracts, multi-branch enforcement table, и явный scope «что в demo есть / чего нет»
- Ссылка добавлена в DE_project main README

### Task #5 — DV2.0 extension (in_progress)
- Foundation ✅ session 1; manifests-in-repo ✅ session 2
- ✅ k8s deployment manifests в `infrastructure/dv2/`: `kind-hq-demo.yaml`, `namespace.yaml`, `secret.example.yaml`, `clickhouse-sts.yaml`, `postgres-sts.yaml`, `bootstrap.sh`, `README.md`
- ✅ **Business Vault слой** (session 3): `business_vault/bv_customer_mdm__msk.sql`, `bv_customer_mdm__dxb.sql`, `bv_order_canonical.sql` — views с argMax SCD2-collapse, per-branch RBAC primitive для MDM, `*_source` columns для conflict-resolution audit. Applied в `hq-demo`: 800/200 msk/dxb customer rows, 10000 orders с branch attribution 40/25/15/10/10. PII/loyalty/header/pricing columns NULL потому что соответствующие satellites не в seed — view-логика проверена, дальнейший прогресс требует satellite seeding или real ETL.
- ✅ **Cold-offload pipeline** (session 3): `infrastructure/dv2/cold-offload-cronjob.yaml` + `warehouse/agentflow/dv2/cold_offload_seed.sql`. PVC `cold-exports` (1Gi) + CronJob `dv2-cold-offload-msk` (cron `0 2 * * *`) → читает только `sat_customer_anon__1c__msk`, пишет Parquet в `/exports/branch=msk/year=2026/month=05/customers_anon.parquet`. Manual Job verified: 800 rows, 20 411 B, 6 anon-колонок, 0 PII (assert grep по schema returns 0).
- ✅ **Satellite seeding + BV verified** (session 3): `warehouse/agentflow/dv2/satellite_seed.sql` заполняет PII/loyalty/header/pricing satellites (sat_customer_personal__1c__msk 800, __1c__dxb 200, sat_customer_loyalty__bitrix__msk 640, sat_order_header__bitrix__msk 4000, sat_order_pricing__1c__msk 4000). После apply `bv_customer_mdm__msk` отдаёт 800 rows с 100% PII / 80% loyalty / 20% pii_only (LEFT JOIN корректно показывает customers без Bitrix); `bv_customer_mdm__dxb` 200 rows с UAE PII; `bv_order_canonical` 4000 msk rows с двумя source-блоками. *_source columns атрибутированы для conflict audit.
- ✅ **DV2.0 расширен на все 5 филиалов** (session 3): spec.yaml +17 satellites, generator вывел 39 DDL (было 22). `warehouse/agentflow/dv2/satellite_seed_all_branches.sql` заполняет spb/ekb/ala customer PII + spb/ekb loyalty + spb/ekb/dxb/ala anon + spb/ekb/dxb/ala order header+pricing. Добавлены `bv_customer_mdm__{spb,ekb,ala}.sql`; `bv_order_canonical` переписан с UNION ALL по всем 5 branch satellites. Verified live: bv_customer_mdm 800/500/300/200/200 (msk/spb/ekb/dxb/ala), bv_order_canonical 4000/2500/1500/1000/1000 с 100% header+pricing coverage, эффективные tax rates 20%/20%/20%/5%/12% (RU/RU/RU/UAE/KZ) автоматически выходят из per-branch 1C сатёллитов.
- ✅ **CronJob fanout** (session 3): `infrastructure/dv2/cold-offload-fanout.yaml` — 4 CronJob клона для spb/ekb/dxb/ala с staggered schedules (msk 02:00, spb 02:30, ekb 03:00, dxb 04:00, ala 05:00).
- ✅ **MinIO S3 swap** (session 3): `infrastructure/dv2/minio.yaml` — single-node MinIO StatefulSet (2Gi PVC) + Service + bucket-init Job. Все 5 CronJob'ов переписаны на `INSERT INTO FUNCTION s3('http://minio:9000/cold-tier/...', ..., 'Parquet')` напрямую через ClickHouse, без PVC mount / `mc cp`. Старый `cold-exports` PVC удалён. Manual MSK+DXB параллельный run: оба Succeeded за ~10с, в bucket лежат `branch=msk/.../customers_anon.parquet 20KiB` + `branch=dxb/.../customers_anon.parquet 6.7KiB`, read-back через `s3()` SELECT count() возвращает 800 / 200. Prod swap = только заменить `Secret/minio-creds` и `S3_ENDPOINT` env на cloud-provider — манифесты не меняются.
- Открытое (deferred — needs explicit user ask):
  - **Argo Workflows** для оркестрации hub → link → satellite загрузки (упомянуто в schema_dv2.md)
  - **dbt models на DV2.0** (опционально — можно показать как mart-layer строится поверх raw vault)
  - **Postgres OLTP populating** — сейчас Postgres pod бежит пустой; для полного дато-flow demo надо seed Postgres OLTP таблицами + настроить PeerDB/Debezium CDC → ClickHouse

### Task #6 — Demo artifacts ✅ DONE (session 2)
- `docs/dv2-multi-branch/demo_evidence.md` — `kubectl get nodes --show-labels`, pod-to-node placement, PVC bind, system.tables breakdown (8/8/22), multi-branch distribution (40/25/15/10/10), query latency (3-4ms на 10K rows), line-items count
- Воспроизводится одной командой: `bash infrastructure/dv2/bootstrap.sh`
- 2-min behavioral pitch (заготовка в `kimi_research.md` § POLISHED LEGEND) — pending, нужен живой запуск
- Optional: запись короткого видео demo — pending

### Технический долг
- ✅ **MD5/unhex gotcha** зафиксирован в `warehouse/agentflow/dv2/README.md` и `infrastructure/dv2/README.md`
- **Mac clock auto-sync**: в новой сессии можно подсказать юзеру `sudo systemsetup -setusingnetworktime on` чтобы часы больше не разъезжались с lima VM
- **K8s persistent storage**: kind использует hostPath provisioner (local-path-storage), при пересоздании кластера данные теряются. Для production-like demo либо deploy через Helm с external PV, либо backup через `kubectl exec ... | clickhouse-client --query "BACKUP ..."` (snippet в `infrastructure/dv2/README.md`).

## Quick-start для следующей сессии

1. Открыть Claude Code в `D:\DE_project`
2. Проверить ветку: `git branch --show-current` → `feat/dv2-multi-branch`
3. Проверить кластер: `ssh julia@192.168.1.133 'kubectl get nodes'`
4. Если нужен контекст — прочитать этот файл
5. Следующая задача — выбрать из «Что осталось» (рекомендую Task #3 → потом #6, потом отполировать #5 до прод-ready)

## Командно-строчный cheat sheet

```bash
# Подключение к кластеру
ssh julia@192.168.1.133

# На маке после ssh:
export PATH=$HOME/lima/bin:$HOME/bin:$PATH

# Проверки
kubectl get nodes --show-labels
kubectl get pods,svc,pvc -n dv2
kubectl describe pod -n dv2 clickhouse-0
kubectl logs -n dv2 clickhouse-0 --tail=50

# ClickHouse shell
kubectl exec -it -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo

# Применить SQL из локального файла
cat /tmp/file.sql | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --multiquery

# Перезапустить deployment (если что-то сломалось)
kubectl rollout restart statefulset/clickhouse -n dv2

# Снести и пересоздать кластер
kind delete cluster --name hq-demo
kind create cluster --config /tmp/kind-hq.yaml
```
