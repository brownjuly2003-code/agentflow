# DV2.0 Multi-Branch — Session Handoff (2026-05-23)

Working snapshot после пяти сессий. Ветка `feat/dv2-multi-branch`
merged в `main` (2026-05-23 afternoon, merge commit `ddfb863`).

> **Session 5 (2026-05-23 afternoon)** — закрыто: per-branch CDC fan-out
> через split на две Postgres-БД (`ops_msk_db`, `ops_dxb_db`) + две
> отдельных CH MaterializedPostgreSQL DB (`oltp_cdc_msk`, `oltp_cdc_dxb`).
> Native обход pitfall #5 (CH 25.5 rejects `materialized_postgresql_publication_name`).
> PeerDB OSS отклонён by hardware constraint — iMac 8 GB RAM не вмещает
> Temporal + flow services поверх живого kind+CH+PG+MinIO+Argo. Артефакты
> в `warehouse/agentflow/dv2/postgres_oltp/fanout/` (4 SQL + README).
> Live verified end-to-end: INSERT/UPDATE в `ops_msk_db` propagated в
> `oltp_cdc_msk` за ~8s, изоляция от DXB подтверждена нулевым cross-leak.
> demo_evidence.md § 15 + handoff отражают новый pattern.

> **Session 4 (2026-05-23 late-morning)** — закрыто:
> behavioral pitch (`pitch.md`), Argo Workflows orchestration (DAG
> поверх hub→link→satellite + 5-way cold-offload + verify), dbt mart
> layer (3 модели + 12 тестов), push-based CDC через
> MaterializedPostgreSQL (single CH DB, multi-schema). Все артефакты
> запущены live на `hq-demo` и зафиксированы в `demo_evidence.md`.
>
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
- ✅ **Postgres OLTP + CDC bridge** (session 3): `warehouse/agentflow/dv2/postgres_oltp/` — `seed.sql` создаёт `ops_msk`/`ops_dxb` schemas в Postgres pod (50+200 / 20+80 customers/orders rows); `bridge.sql` создаёт 4 ClickHouse-таблицы с `Engine = PostgreSQL(...)` live read-through; `promote_to_raw_vault.sql` промоутит OLTP → `rv.hub_customer/hub_order/lnk_order_customer/sat_*` с record_source `pg_ops__{branch}`. Verified: 280 OLTP-* orders видны в `bv_order_canonical` с корректным branch attribution. Convention bug fix: одинарное `pg_ops_msk` ломало `splitByString('__', ...)[2]`, переписано на double-underscore.
- ✅ **Argo Workflows** (session 4) — `infrastructure/dv2/argo/` (install.sh + RBAC + WorkflowTemplate `dv2-refresh`). DAG: promote-oltp → validate-hubs → (validate-links, validate-satellites) → cold-offload-fanout(5) → verify-mirrors. Live run `dv2-refresh-xwnb8` 73s end-to-end; verify-mirrors output `msk=800/spb=500/ekb=300/dxb=200/ala=200 OK`. Шаги `validate-satellites` и `verify-mirrors` использовали FINAL на сателлитах изначально — поймал ILLEGAL_FINAL (сателлиты = MergeTree, не ReplacingMergeTree), fix landed.
- ✅ **dbt mart layer** (session 4) — `warehouse/agentflow/dv2/dbt/` + `infrastructure/dv2/dbt/`. 3 модели (customer_360, branch_pnl, returns_velocity) поверх `rv.bv_*`. 12 data tests (not_null + accepted_values('msk','spb','ekb','dxb','ala')). Live run `kubectl logs job/dbt-run-marts`: `PASS=3 ERROR=0` (run) + `PASS=12 ERROR=0` (test). effective_tax_rate per branch: ala=0.12 / dxb=0.05 / msk-spb-ekb=0.20. Pitfall: `+schema: marts` в `dbt_project.yml` + `schema: marts` в profile → tables landed в `marts_marts` вместо `marts`; убрал `+schema`.
- ✅ **MaterializedPostgreSQL push-based CDC** (session 4) — `warehouse/agentflow/dv2/postgres_oltp/cdc_{setup,bridge}.sql` + `promote_to_raw_vault_cdc.sql`. Postgres: `wal_level=logical` в `postgres-sts.yaml`, rep_user + REPLICA IDENTITY DEFAULT + ALTER TABLE OWNER, ALTER. ClickHouse: single `oltp_cdc` DB через `materialized_postgresql_schema_list='ops_msk,ops_dxb'`. Live E2E: INSERT/UPDATE в Postgres → видно в `oltp_cdc.\`ops_msk.customers\` FINAL` за ~5s без `INSERT INTO ... SELECT` на CH-стороне. Row parity Postgres=ClickHouse (msk 57=57, dxb 24=24).
  - Pitfalls собрано: (1) `MaterializedPostgreSQL` experimental → нужен `SET allow_experimental_database_materialized_postgresql=1`; (2) rep_user нужен CONNECT + CREATE на БД, OWNER на таблицах (CH делает `CREATE PUBLICATION ... FOR TABLE`); (3) `REPLICA IDENTITY FULL` НЕ поддерживается → нужен DEFAULT (PK); (4) `materialized_postgresql_replication_slot=` требует pre-existing slot, иначе CH сам автосоздаёт; (5) `materialized_postgresql_publication_name` НЕ существует — два CH DB на одной PG DB конфликтуют на дефолтном `<src>_ch_publication`; решение — single CH DB + schema_list (или PeerDB/Debezium для полной изоляции).
- ✅ **Per-branch CDC fan-out** (session 5) — `warehouse/agentflow/dv2/postgres_oltp/fanout/` (01_schema/02_seed/03_cdc_setup/04_ch_bridge + README). Two new Postgres databases `ops_msk_db` (10 cust / 30 orders seed) + `ops_dxb_db` (8 / 20) → two CH databases `oltp_cdc_msk` + `oltp_cdc_dxb`. Auto-named publications no longer collide because source DB name differs. Live verified: INSERT/UPDATE in `ops_msk_db` propagated within ~8s, zero cross-leak from DXB visible in MSK CH DB, two distinct replication slots `ops_msk_db` + `ops_dxb_db` (separate from session-4 `ops` slot). PeerDB OSS was the originally-planned route but its ~3 GB stack (Temporal + cassandra/elasticsearch + flow services + catalog PG) does not fit on the 8 GB demo iMac alongside existing kind + ClickHouse + Postgres + MinIO + Argo. Per-DB split delivers the same architectural property (per-branch isolation) natively. See `fanout/README.md` § "Why not PeerDB" for the reasoning, `demo_evidence.md` § 15 for the live evidence.
- Открытое (deferred — needs explicit user ask):

### Task #6 — Demo artifacts ✅ DONE (sessions 2 + 4)
- `docs/dv2-multi-branch/demo_evidence.md` — 14 секций: cluster topology, pod placement, DV2.0 model surface, multi-branch distribution, latency, BV MDM, cold-offload + MinIO, Postgres OLTP, Argo run, dbt run, CDC E2E
- Воспроизводится одной командой: `bash infrastructure/dv2/bootstrap.sh`
- ✅ **2-min behavioral pitch** (session 4) — `docs/dv2-multi-branch/pitch.md`: 6 beats × 15-25s с live `kubectl` cues для каждого. Спутник к demo_evidence.md
- ✅ **Voice-over MP4 demo** (session 6, 2026-05-23) — `docs/dv2-multi-branch/demo_voiced.mp4` (~92 s, 3.2 MB). Cast `demo.cast` слоумо до длины русской TTS-narration по pitch.md (ru-RU-SvetlanaNeural, +25%). Reproducible через `docs/dv2-multi-branch/demo_voiced.build.sh` + `demo_voiced.narration.txt` (требует edge-tts, ffmpeg, agg).

### Технический долг
- ✅ **MD5/unhex gotcha** зафиксирован в `warehouse/agentflow/dv2/README.md` и `infrastructure/dv2/README.md`
- **Mac clock auto-sync**: в новой сессии можно подсказать юзеру `sudo systemsetup -setusingnetworktime on` чтобы часы больше не разъезжались с lima VM
- **K8s persistent storage**: kind использует hostPath provisioner (local-path-storage), при пересоздании кластера данные теряются. Для production-like demo либо deploy через Helm с external PV, либо backup через `kubectl exec ... | clickhouse-client --query "BACKUP ..."` (snippet в `infrastructure/dv2/README.md`).

## Quick-start для следующей сессии

1. Открыть Claude Code в `D:\DE_project`
2. Проверить ветку: `git branch --show-current` → `main`, HEAD includes merge `ddfb863` (session 5 closed, feat/dv2-multi-branch merged)
3. Проверить кластер: `ssh julia@192.168.1.133 'PATH=$HOME/lima/bin:$HOME/bin:$PATH kubectl get pods -n dv2 && kubectl get pods -n argo'`
   - **Ожидаемое:** clickhouse-0 / postgres-0 / minio-0 Running в `dv2`; argo-server + workflow-controller Running в `argo`; `oltp_cdc.*` 4 таблицы видны через CH-клиент; `oltp_cdc_msk.*` + `oltp_cdc_dxb.*` per-branch fan-out таблицы видны
4. Контекст — этот файл + `demo_evidence.md` (§12-15 свежее) + `pitch.md`
5. Открытые задачи (deferred, нужен явный ask): **запись live screencast** поверх работающего кластера — текущий `demo_voiced.mp4` это слоумо терминала + TTS; видео с web UI (Argo UI / dbt docs / MinIO console) ещё не снято

## Current cluster state (на момент закрытия session 5, 2026-05-23)

Применено на `hq-demo`:
- ✅ baseline DV2.0 stack: 3 ноды kind, ClickHouse 25.5 + Postgres 17 + MinIO StatefulSets, 38 rv.* таблиц + 5 BV views + `marts.*` (dbt)
- ✅ 5 cold-offload CronJobs (msk/spb/ekb/dxb/ala, MinIO бэкэнд)
- ✅ Argo Workflows v3.5.10 в namespace `argo` + WorkflowTemplate `dv2-refresh` в `dv2` (post-session-4 rerun `dv2-refresh-spzhf` 90s end-to-end Succeeded, ILLEGAL_FINAL fix verified)
- ✅ Postgres `wal_level=logical` + 3 logical replication slots (`ops` для session-4 single-DB + `ops_msk_db` + `ops_dxb_db` для session-5 fan-out)
- ✅ ClickHouse `oltp_cdc` database (MaterializedPostgreSQL) активно стримит `ops_msk` + `ops_dxb` schemas (single-DB pattern)
- ✅ ClickHouse `oltp_cdc_msk` + `oltp_cdc_dxb` databases (session-5 per-branch fan-out, each bound to its own Postgres database `ops_msk_db` / `ops_dxb_db`)
- ✅ dbt marts: `marts.{customer_360,branch_pnl,returns_velocity}` материализованы

## Полная пересборка с нуля (если кластер потерян)

```bash
ssh julia@192.168.1.133
export PATH=$HOME/lima/bin:$HOME/bin:$PATH
limactl start docker            # если Lima VM не запущена

# Step 1: baseline (kind + CH + PG + MinIO + DDL + seed + cold-offload CronJobs)
bash infrastructure/dv2/bootstrap.sh

# Step 2: Argo Workflows + WorkflowTemplate
bash infrastructure/dv2/argo/install.sh

# Step 3: push-based CDC (требует postgres-sts.yaml с wal_level=logical — уже в baseline после session 4)
# 3.1 Postgres-side: rep_user + grants + REPLICA IDENTITY DEFAULT + table ownership
cat warehouse/agentflow/dv2/postgres_oltp/cdc_setup.sql \
  | kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops
# 3.2 ClickHouse-side: oltp_cdc DB
cat warehouse/agentflow/dv2/postgres_oltp/cdc_bridge.sql \
  | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --multiquery
# 3.3 Promote CDC OLTP rows → raw_vault (one-shot после первого snapshot)
cat warehouse/agentflow/dv2/postgres_oltp/promote_to_raw_vault_cdc.sql \
  | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --multiquery

# Step 4: dbt marts (с Windows-машины — нужны файлы из репо)
cd /d/DE_project/warehouse/agentflow/dv2/dbt
tar -czf /tmp/dbt-project.tar.gz dbt_project.yml profiles.example.yml models README.md
scp /tmp/dbt-project.tar.gz julia@192.168.1.133:/tmp/dbt-project.tar.gz
ssh julia@192.168.1.133 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH && \
  kubectl create configmap dbt-project -n dv2 --from-file=project.tar.gz=/tmp/dbt-project.tar.gz --dry-run=client -o yaml | kubectl apply -f -'
cat /d/DE_project/infrastructure/dv2/dbt/dbt-run-job.yaml \
  | ssh julia@192.168.1.133 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH && kubectl apply -f -'

# Step 5 (опционально): submit Argo workflow для end-to-end refresh
ssh julia@192.168.1.133 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH && cat <<EOF | kubectl create -n dv2 -f -
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata: {generateName: dv2-refresh-}
spec: {workflowTemplateRef: {name: dv2-refresh}}
EOF'

# Step 6: per-branch CDC fan-out (session 5)
for f in 01_schema 02_seed 03_cdc_setup; do
  cat warehouse/agentflow/dv2/postgres_oltp/fanout/${f}.sql \
    | kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres
done
cat warehouse/agentflow/dv2/postgres_oltp/fanout/04_ch_bridge.sql \
  | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo --multiquery
```

Время полной пересборки на iMac 2017 ~10-12 минут (kind + image pulls).

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
