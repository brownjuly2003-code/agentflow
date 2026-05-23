# DV2.0 Multi-Branch — Session Handoff (2026-05-23)

Working snapshot после первой сессии. Ветка `feat/dv2-multi-branch`.

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
  - K8s manifest: NOT committed yet (был inline в bash), нужно вынести в `helm/dv2/` или `infrastructure/dv2/`

## Что осталось

### Task #3 — End-to-end data flow diagram (pending)
- Mermaid или ASCII диаграмма: источники → Postgres OLTP → CDC → ClickHouse DV2.0 → cold offload в S3-compatible
- Можно встроить в DE_project main README или в `docs/architecture.md`
- Оценка: 1-2 часа

### Task #5 — DV2.0 extension (in_progress, foundation done)
- Foundation: ✅ закрыт этой сессией
- Открытое:
  - **k8s deployment manifests** вынести из inline bash в `helm/dv2/` chart или `infrastructure/dv2/*.yaml` (сейчас живёт только в running cluster и в SESSION_HANDOFF)
  - **Argo Workflows** для оркестрации hub → link → satellite загрузки (упомянуто в schema_dv2.md)
  - **Cold-offload CronJob** для anonymized parquet → HF Datasets (или MinIO в pod как cloud mock)
  - **Business Vault слой** (`bv_customer_mdm`, `bv_order_canonical`) — placeholder создан, контент нужен
  - **dbt models на DV2.0** (опционально — можно показать как mart-layer строится поверх raw vault)

### Task #6 — Demo artifacts (pending)
- Скриншоты: `kubectl get all -A`, `kubectl describe nodes` (показывает labels/placement), Grafana если поставим, query results
- Architecture diagram (visual)
- 2-min behavioral pitch (заготовка в `kimi_research.md` § POLISHED LEGEND)
- README в DE_project main updates: добавить раздел про DV2.0 multi-branch extension
- Optional: запись короткого видео demo (kubectl + clickhouse-client + BI query)

### Технический долг
- **Не использовать `unhex(MD5(x))`** в ClickHouse SQL — `MD5(x)` уже возвращает FixedString(16). Зафиксировать в README или CONTRIBUTING.
- **Mac clock auto-sync**: в новой сессии можно подсказать юзеру `sudo systemsetup -setusingnetworktime on` чтобы часы больше не разъезжались с lima VM.
- **K8s persistent storage**: kind использует hostPath provisioner (local-path-storage), при пересоздании кластера данные теряются. Для production-like demo либо deploy через Helm с external PV, либо backup через `kubectl exec ... | clickhouse-client --query "BACKUP ..."`.

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
