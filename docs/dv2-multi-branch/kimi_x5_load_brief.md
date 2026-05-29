# Задача: загрузить реальные X5 Retail Hero данные в DV2.0 demo и переписать demo-evidence + pitch против настоящих цифр

## Контекст

`D:\DE_project\` — AgentFlow + DV2.0 multi-branch demo (portfolio проект Julia
Edomskikh для job-search). main HEAD `4625222`, working tree clean.

DV2.0 хранилище живёт в self-hosted **kind кластере на iMac**
`julia@192.168.1.133` (Lima VM, namespace `dv2`). ClickHouse 25.x +
Postgres 17 + MinIO. SSH-доступ работает. DV2.0 DDL уже применён в БД
`rv`.

Сейчас демо использует `warehouse/agentflow/dv2/synthetic_seed.sql` —
10 000 заказов / 24 938 line items / 4 000 orders. Все цифры в
`docs/dv2-multi-branch/demo_evidence.md` и `pitch.md` — из synthetic.

**Loader для реальных X5 данных уже написан и не запускался:**
`warehouse/agentflow/dv2/loaders/x5_retail_hero/loader.py` (~750 LOC,
7 файлов). README:
`warehouse/agentflow/dv2/loaders/x5_retail_hero/README.md`.

Цель — заменить synthetic на ~45.8M реальных X5 транзакций /
~400K клиентов так, чтобы demo-evidence и pitch ссылались на настоящие
числа.

## Что сделать

### 1. Скачать датасет

Kaggle CLI установлен у пользователя (использовался для ROGII). На
WSL/локальной машине либо на iMac:

```bash
kaggle datasets download -d mvyurchenko/x5-retail-hero \
    -p /path/to/x5 --unzip
```

Ожидаемые файлы: `clients.csv`, `products.csv`, `purchases.csv`.
Распакованный размер ~3-4 GB.

### 2. Доставить CSV на iMac

```bash
scp -r /path/to/x5 julia@192.168.1.133:/Users/julia/x5/
```

или (если место на iMac позволяет) — скачать прямо на iMac через
Kaggle CLI там.

### 3. Запустить loader из пода ClickHouse-клиента

DV2.0 namespace = `dv2`. ClickHouse доступен внутри кластера как
`clickhouse-0.clickhouse.dv2.svc.cluster.local:9000`. Loader умеет
бить на батчи 100K строк; для покрытия `purchases.csv` нужно ~458
батчей.

Варианты запуска:

(a) `kubectl -n dv2 cp` CSV-ы в под и запустить loader там:

```bash
kubectl -n dv2 cp /Users/julia/x5 dv2/clickhouse-0:/tmp/x5
kubectl -n dv2 exec clickhouse-0 -- \
    python /path/to/loader.py \
        --csv-dir /tmp/x5 \
        --clickhouse-host localhost \
        --clickhouse-port 9000 \
        --batch-size 100000 \
        --load-ts 2026-05-26T00:00:00Z
```

(b) Или с iMac через port-forward:

```bash
kubectl -n dv2 port-forward svc/clickhouse 9000:9000 &
python warehouse/agentflow/dv2/loaders/x5_retail_hero/loader.py \
    --csv-dir /Users/julia/x5 \
    --clickhouse-host localhost \
    --clickhouse-port 9000 \
    --batch-size 100000 \
    --load-ts 2026-05-26T00:00:00Z
```

Lima VM single-CPU; ingest 45.8M строк ожидаемо ~30-60 минут. Если
loader падает на OOM/timeout — снизить batch-size до 50000.

### 4. Верифицировать после загрузки

Через `kubectl -n dv2 exec clickhouse-0 -- clickhouse-client -q '...'`:

```sql
SELECT count() FROM rv.hub_customer;
SELECT count() FROM rv.hub_product;
SELECT count() FROM rv.hub_store;
SELECT count() FROM rv.hub_order;
SELECT count() FROM rv.lnk_order_product;
SELECT count() FROM rv.sat_customer_personal__1c__msk;
SELECT count() FROM rv.sat_customer_personal__1c__spb;
SELECT count() FROM rv.sat_customer_personal__1c__ekb;
SELECT count() FROM rv.sat_customer_personal__1c__dxb;
SELECT count() FROM rv.sat_customer_personal__1c__ala;

-- Branch split проверка
SELECT splitByChar('-', store_bk)[1] AS branch,
       count() AS stores
FROM rv.hub_store
GROUP BY branch
ORDER BY stores DESC;
```

**Ожидаемые порядки:**

- `hub_customer` ≥ 400 000
- `hub_product` ~40 000
- `hub_store` несколько сотен
- `hub_order` ≥ 5-10M (unique transactions)
- `lnk_order_product` ≥ 45M
- Branch split (по магазинам) близко к 40/25/15/10/10, допустимо ±3pp

### 5. Переписать demo_evidence.md

Файл `docs/dv2-multi-branch/demo_evidence.md` сейчас цитирует
synthetic-числа (10K / 24938 / 4000). Заменить на реальные из шага 4.
Сохранить структуру (sections 1-8), но цифры — из живого кластера.

Сравнительная query (sections 6 «Latency floor», 7 «Line items reach»,
8 «Business Vault — populated views») — re-run против реального
объёма и вставить новые `query_duration_ms` / `read_rows` из
`system.query_log`. Sub-second агрегации в ClickHouse под Lima на
45M строк должны держаться на ~50-200 ms — это и есть demo-value.

### 6. Обновить pitch.md

`docs/dv2-multi-branch/pitch.md` — beat 4 (multi-branch GROUP BY) и
beat 6 (cold-offload) сейчас написаны под synthetic-объём. Под X5:

- beat 4 query должен возвращать non-trivial top-N по реальным
  product/branch агрегациям (например, top-10 product_id по сумме
  чеков в MSK vs DXB)
- beat 7 (session-5 fan-out) — добавить counts из per-branch CDC

Narration в `demo_voiced.narration.txt` / `demo_webui.narration.txt`
переписывать не обязательно — повторная запись TTS требует ffmpeg
pipeline и edge-tts. Если время позволяет — re-render через
`demo_voiced.build.sh` и `demo_webui.capture.py`. Если нет —
оставить ссылку «volumes refreshed against real X5 Retail Hero
data — see demo_evidence.md».

### 7. Закоммитить

```
git checkout -b feat/dv2-x5-real-data
# edits...
git add -A
git commit -m "feat(dv2): load X5 Retail Hero real data, refresh demo evidence

* warehouse/agentflow/dv2/loaders/x5_retail_hero/ executed against
  Kaggle dataset mvyurchenko/x5-retail-hero, load_ts
  2026-05-26T00:00:00Z
* rv.hub_customer ~400K, rv.lnk_order_product ~45M, branch split
  40/25/15/10/10 within ±3pp
* demo_evidence.md cited counts and ClickHouse query_duration_ms
  refreshed against live cluster
* pitch.md beats 4 + 7 rewired to non-trivial real-data queries
* synthetic_seed.sql preserved as fast-dev seed (kept in tree)
"
git push origin feat/dv2-x5-real-data
gh pr create --title "DV2 demo: real X5 Retail Hero data" \
  --body "..." 
```

**Не удалять** `synthetic_seed.sql` — оставить как быстрый dev-seed
для воспроизводимости без 4GB CSV. Просто перестать ссылаться на него
в demo-evidence.

## Что НЕ делать

- Не загружать датасет Lenta BigTarget — это отдельный uplift-проект,
  не вписывается в DV2.0 sales-vault schema из коробки.
- Не пересобирать Argo Workflows / dbt — текущие модели в
  `warehouse/agentflow/dv2/dbt/` рассчитаны на data-volume agnostic
  и сами подхватят больший fact-table.
- Не пушить в `main` напрямую (исторически делалось owner-bypass,
  но эта работа — feature branch + PR, чтобы у живых демо
  оставалась чистая ссылка «before/after X5 ingest»).

## Готовность

- Loader smoke (`python loader.py --dry-run --csv-dir <X5>`) проходит
- 6 row-count queries возвращают значения из таблицы выше
- demo_evidence.md показывает реальные числа + свежие
  `query_duration_ms`
- pitch.md beats 4 + 7 переписаны
- PR открыт, CI зелёный

## Outputs

- `feat/dv2-x5-real-data` ветка + PR URL
- Лог загрузки (stdout/stderr loader + ingest duration)
- Diff `demo_evidence.md` / `pitch.md` (числа до/после)
- 6 row-count queries и их результаты в комментарии PR
