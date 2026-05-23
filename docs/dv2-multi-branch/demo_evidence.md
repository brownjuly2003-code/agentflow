# DV2.0 Multi-Branch — Live Demo Evidence

Captured against the running `hq-demo` cluster on the iMac demo host
(192.168.1.133) on 2026-05-23. Every block is reproducible from
`infrastructure/dv2/bootstrap.sh`.

## 1. Cluster topology — `kubectl get nodes --show-labels`

```
NAME                    STATUS   ROLES           AGE   VERSION
hq-demo-control-plane   Ready    control-plane   77m   v1.35.0
hq-demo-worker          Ready    <none>          76m   v1.35.0
hq-demo-worker2         Ready    <none>          76m   v1.35.0
```

Labels decoded:

| Node                    | branch | nodepool         | workload    |
| ----------------------- | ------ | ---------------- | ----------- |
| hq-demo-control-plane   | msk    | hq-control       | —           |
| hq-demo-worker          | msk    | hq-data-tier-a   | postgres    |
| hq-demo-worker2         | msk    | hq-data-tier-b   | clickhouse  |

## 2. Workload pinning — `kubectl get pods -n dv2 -o custom-columns=POD,NODE`

```
POD            NODE              STATUS
clickhouse-0   hq-demo-worker2   Running
postgres-0     hq-demo-worker    Running
```

`nodeSelector: workload=clickhouse|postgres` on each StatefulSet enforces the
placement — the same primitive that production would use to pin per-branch
edge nodes (`branch=dxb`, `branch=ala`).

## 3. Persistent storage — `kubectl get pvc -n dv2`

```
NAME                STATUS   CAPACITY   ACCESS MODES   STORAGECLASS
data-clickhouse-0   Bound    5Gi        RWO            standard
data-postgres-0     Bound    2Gi        RWO            standard
```

## 4. DV2.0 model surface — `system.tables` grouped by family

38 tables in database `rv`:

```
hub_*               8   (customer, product, order, shipment, store, supplier, employee, marking_code)
lnk_*               8   (order_customer, order_product, order_store, order_employee,
                         order_shipment, shipment_store, product_supplier, product_marking)
sat_*              22   (per-source × per-branch satellites; full matrix in spec.yaml)
```

## 5. Multi-branch distribution proof

```sql
SELECT
  splitByString('__', record_source)[2] AS branch,
  count() AS orders,
  round(count() * 100.0 / (SELECT count() FROM rv.hub_order), 1) AS pct
FROM rv.hub_order
GROUP BY branch ORDER BY pct DESC;
```

```
┌─branch─┬─orders─┬─pct─┐
│ msk    │   4000 │  40 │
│ spb    │   2500 │  25 │
│ ekb    │   1500 │  15 │
│ dxb    │   1000 │  10 │
│ ala    │   1000 │  10 │
└────────┴────────┴─────┘
```

The 40/25/15/10/10 split lines up with the consistent-hashing distribution
that the X5 Retail Hero loader (`warehouse/agentflow/dv2/loaders/x5_retail_hero/`)
applies to real transactions when seeded against the production-volume CSVs.

## 6. Latency floor — multi-branch aggregation

`SYSTEM FLUSH LOGS; SELECT query_duration_ms, read_rows FROM system.query_log
WHERE query LIKE '%hub_order%' ORDER BY event_time DESC LIMIT 3`:

```
┌─query_duration_ms─┬─read_rows─┐
│                 3 │     10000 │
│                 4 │     10001 │
│                 4 │     10000 │
└───────────────────┴───────────┘
```

3–4 ms for a multi-branch GROUP BY over 10K hub rows on a kind-on-Lima
single-CPU container — well inside BI-acceptable budgets, with headroom for
hash-join expansion via satellites.

## 7. Line items reach

```sql
SELECT count() FROM rv.lnk_order_product;  -- 24938
```

Matches the seed's 2.5× average line items per order.

## 8. Business Vault — populated views with MDM conflict resolution

`warehouse/agentflow/dv2/satellite_seed.sql` populates the customer / order
satellites that `synthetic_seed.sql` deliberately leaves empty. After applying:

```
sat_customer_personal__1c__msk      800 rows  (msk slice)
sat_customer_personal__1c__dxb      200 rows  (dxb slice)
sat_customer_loyalty__bitrix__msk   640 rows  (80% loyalty coverage)
sat_order_header__bitrix__msk      4000 rows  (msk slice)
sat_order_pricing__1c__msk         4000 rows  (msk slice)
```

`bv_customer_mdm__msk` (PII from 1C, loyalty from Bitrix):

```
rows | with_pii | with_loyalty | pii_only | loyalty_only
 800 |      800 |          640 |      160 |            0
```

The 160 `pii_only` rows are msk customers without a Bitrix profile yet — the
LEFT JOIN keeps them visible with `loyalty_source = NULL`, exactly as the
view contract documents.

Sample (PII + loyalty merged for the same `customer_hk`):

```
Ivan   Volkov   cust236@example.test  gold     3068  pii=1c__msk  loy=bitrix__msk
Egor   Petrov   cust833@example.test  bronze  10829  pii=1c__msk  loy=bitrix__msk
Lena   Sidorov  cust138@example.test  bronze   1794  pii=1c__msk  loy=bitrix__msk
```

`bv_customer_mdm__dxb` returns 200 rows with Arabic-style faux PII, all
tagged `pii=1c__dxb`. The MSK view never returns them — the per-branch view
+ RBAC primitive is what enforces jurisdictional isolation here.

All five `bv_customer_mdm__*` views populated (after extending spec.yaml +
satellite_seed_all_branches.sql):

```
branch  rows  with_pii  with_loyalty
ala      200       200            0    (KZ — no Bitrix loyalty by design)
dxb      200       200            0    (UAE — no Bitrix loyalty by design)
ekb      300       300          240    (80% loyalty coverage)
msk      800       800          640
spb      500       500          400
```

`bv_order_canonical` now joins Bitrix header + 1C pricing across every
branch (the view UNION ALL's all five `sat_order_header__bitrix__*` and
`sat_order_pricing__1c__*` satellites):

```
branch  orders  with_header  with_pricing
msk      4000        4000         4000
spb      2500        2500         2500
ekb      1500        1500         1500
dxb      1000        1000         1000
ala      1000        1000         1000
```

The jurisdiction-specific tax rates fall straight out of per-branch 1C
satellites — one BI query exercises the entire multi-branch model:

```sql
SELECT branch,
       round(avg(toFloat64(tax_amount) / nullIf(toFloat64(subtotal_amount), 0)), 4) AS rate
FROM rv.bv_order_canonical
WHERE subtotal_amount > 0 AND tax_amount IS NOT NULL
GROUP BY branch ORDER BY branch;
```

```
ala  0.12   (KZ VAT 12%)
dxb  0.05   (UAE VAT 5%)
ekb  0.20   (RU VAT 20%)
msk  0.20   (RU VAT 20%)
spb  0.20   (RU VAT 20%)
```

Sample ALA rows showing localised attribution:

```
ala  retail       returned   6498   tax=779.76    header=bitrix__ala  pricing=1c__ala
ala  call-center  returned   8083   tax=969.95    header=bitrix__ala  pricing=1c__ala
ala  retail       returned  14798   tax=1775.76   header=bitrix__ala  pricing=1c__ala
```

## 9. Cold-offload pipeline — MinIO S3 backed

`infrastructure/dv2/minio.yaml` provisions a single-node MinIO
StatefulSet + Service + bucket-init Job. The cold-offload CronJobs
(`infrastructure/dv2/cold-offload-cronjob.yaml` + `cold-offload-fanout.yaml`)
write parquet straight into the `cold-tier` bucket via ClickHouse's native
`s3()` table function — no intermediate PVC, no `mc cp` step.

Bucket layout after running MSK + DXB jobs:

```
mc ls -r local/cold-tier
[2026-05-23 06:48:48 UTC] 6.7KiB  branch=dxb/year=2026/month=05/customers_anon.parquet
[2026-05-23 06:48:53 UTC]  20KiB  branch=msk/year=2026/month=05/customers_anon.parquet
```

Each pod runs the same two-statement contract — write then verify — so
the success of the read-back implicitly asserts:

1. ClickHouse can reach the MinIO Service inside the dv2 namespace.
2. The bucket accepts an INSERT INTO FUNCTION s3('...', 'Parquet') call.
3. The same s3() call reading the file back parses the parquet schema.

MSK + DXB triggered in parallel (`kubectl create job
--from=cronjob/dv2-cold-offload-{msk,dxb}`) finished in ~10 s. Logs:

```
==> exporting branch=msk -> http://minio:9000/cold-tier/branch=msk/year=2026/month=05/customers_anon.parquet
==> done; verifying via s3() read-back
800
```

```
200    # dxb job
```

A schema grep for `first_name|last_name|email|phone|birth_date|pii_flag`
returns 0 — the data-sovereignty contract from `architecture.md` is enforced
by source selection (`sat_customer_anon__1c__{branch}` is the only
satellite the CronJob reads).

### Branch fanout

`cold-offload-fanout.yaml` clones MSK for the four remaining branches.
Schedules are staggered (msk 02:00, spb 02:30, ekb 03:00, dxb 04:00,
ala 05:00) so MinIO isn't hammered by five concurrent writes; in real
prod they'd run in parallel via per-branch edge clusters, not a single
cluster as here.

### Production swap path

The CronJob takes `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` from
env vars — point them at a real S3 / GCS / Yandex Object Storage and the
`s3()` function works unchanged. The `Secret/minio-creds` resource drops
out, the cloud-provider secret takes its place, and the rest of the
manifest is untouched. Add `WHERE load_ts < now() - INTERVAL 365 DAY` to
the SELECT in prod.

## 10. Hot tier — Postgres OLTP + ClickHouse PostgreSQL() bridge

`warehouse/agentflow/dv2/postgres_oltp/seed.sql` populates the
previously-empty Postgres pod with `ops_msk` + `ops_dxb` schemas
(customers + orders, 50/200 and 20/80 rows respectively).
`bridge.sql` creates four `oltp_live.{msk,dxb}_{customers,orders}`
tables in ClickHouse using `Engine = PostgreSQL(...)` — live
read-through of the OLTP tables, no replication slot required.
`promote_to_raw_vault.sql` runs the hot → warm step.

Live join across the bridge — ClickHouse SELECTs Postgres rows
directly:

```sql
SELECT o.order_id, o.channel, o.total_amount, c.first_name, c.last_name
FROM oltp_live.msk_orders o
JOIN oltp_live.msk_customers c ON o.customer_id = c.customer_id
ORDER BY o.order_id LIMIT 3;
```

```
OLTP-MSK-000001  mobile       531  Dasha   Sidorov
OLTP-MSK-000002  retail       562  Egor    Smirnov
OLTP-MSK-000003  call-center  593  Fedor   Volkov
```

After the promote step `rv.hub_order` gains two new `record_source`
values (`pg_ops__msk` 200 rows, `pg_ops__dxb` 80) and the existing
1C-seeded volumes are untouched:

```
1c__msk      4000
1c__spb      2500
1c__ekb      1500
1c__ala      1000
1c__dxb      1000
pg_ops__msk   200
pg_ops__dxb    80
```

End-to-end check — Postgres orders surface inside `bv_order_canonical`
with correct branch attribution and `header_source` matching the
destination satellite:

```
order_bk          branch  channel       total   header_source
OLTP-MSK-000144   msk     web            4964   bitrix__msk
OLTP-MSK-000127   msk     call-center    4437   bitrix__msk
OLTP-MSK-000195   msk     call-center    6545   bitrix__msk
```

The trip from Postgres → ClickHouse OLTP-bridge → raw_vault →
business_vault is the same code path a real Debezium / PeerDB consumer
would land on; the engine swap (`PostgreSQL` → `MaterializedPostgreSQL`
or a streaming CDC writer) preserves the rest of the model untouched.

## 11. How to re-run on the same cluster

```bash
ssh julia@192.168.1.133
export PATH=$HOME/lima/bin:$HOME/bin:$PATH
kubectl exec -it -n dv2 clickhouse-0 -- clickhouse-client \
  --user default --password demo --database rv
```

Or, from this repo on any host with `kubectl` context pointing at the
cluster:

```bash
bash infrastructure/dv2/bootstrap.sh   # idempotent rebuild
```

## 12. Argo Workflows orchestration

`infrastructure/dv2/argo/` deploys Argo Workflows v3.5.10 cluster-scope
plus a `dv2-refresh` WorkflowTemplate that chains the previously
standalone hot → warm → cold steps as one DAG:

```
promote-oltp
    │
validate-hubs
    │
    ├─ validate-links
    │       │
    │       └────────────┐
    └─ validate-satellites
                          │
              cold-offload (fan-out: msk, spb, ekb, dxb, ala)
                          │
                  verify-mirrors
```

End-to-end run on the live cluster (`dv2-refresh-xwnb8`, 73 s total
wall):

```
promote-oltp           Succeeded   2026-05-23T08:19:31 -> 08:19:36
validate-hubs          Succeeded   2026-05-23T08:19:41 -> 08:19:46
validate-links         Succeeded   2026-05-23T08:19:51 -> 08:19:56
validate-satellites    Succeeded   2026-05-23T08:19:51 -> 08:19:57
cold-offload(0:msk)    Succeeded   2026-05-23T08:20:01 -> 08:20:25
cold-offload(1:spb)    Succeeded   2026-05-23T08:20:01 -> 08:20:15
cold-offload(2:ekb)    Succeeded   2026-05-23T08:20:01 -> 08:20:25
cold-offload(3:dxb)    Succeeded   2026-05-23T08:20:01 -> 08:20:14
cold-offload(4:ala)    Succeeded   2026-05-23T08:20:01 -> 08:20:26
verify-mirrors         Succeeded   2026-05-23T08:20:34 -> 08:20:38
```

`verify-mirrors` step output (capture run `dv2-refresh-capture-s27ng`):

```
==> cross-checking mirrors vs source satellites
    msk  source=800    mirror=800    OK
    spb  source=500    mirror=500    OK
    ekb  source=300    mirror=300    OK
    dxb  source=200    mirror=200    OK
    ala  source=200    mirror=200    OK
==> all 5 mirrors match source
```

Layer ordering (hub → link → satellite → cold-offload) is enforced by
DAG dependencies — not by clock-time as the standalone CronJobs do.
A failure in `validate-links` aborts the run before any S3 write, so
mirrors are never out of sync with the warm tier.

## 13. dbt mart layer

`warehouse/agentflow/dv2/dbt/` ships three materialized marts and 12
data tests on top of the business vault. Project files are mounted into
a Kubernetes Job (`infrastructure/dv2/dbt/dbt-run-job.yaml`) via a
ConfigMap built from the repo by `infrastructure/dv2/dbt/run.sh`.

Run summary (from `kubectl logs job/dbt-run-marts`):

```
Done. PASS=3   WARN=0  ERROR=0  SKIP=0  TOTAL=3      (dbt run)
Done. PASS=12  WARN=0  ERROR=0  SKIP=0  TOTAL=12     (dbt test)
```

`customer_360` populated per branch — one row per `(customer_hk, branch)`:

```
branch  rows  with_orders  avg_ltv
ala      200          84    6554.1
dxb      200          84    7002.4
ekb      300         157    9212.4
msk      800         694   25496.5
spb      500         366   16784.5
```

`branch_pnl.effective_tax_rate` validates the per-jurisdiction wiring
end-to-end (1C pricing satellites → BV view → dbt mart):

```
branch  rate
ala     0.12   (KZ VAT 12%)
dxb     0.05   (UAE VAT 5%)
ekb     0.20   (RU VAT 20%)
msk     0.20   (RU VAT 20%)
spb     0.20   (RU VAT 20%)
```

The 12 dbt tests cover `not_null` on key columns
(`customer_hk`, `branch`, `month`, `channel`, `week`, `return_rate`)
and `accepted_values` on `branch` (must be one of msk/spb/ekb/dxb/ala)
across all three marts.

## 14. Push-based CDC via MaterializedPostgreSQL

The pull-based `oltp_live` bridge (Postgres-engine table mirrors) is
replaced by a single `oltp_cdc` ClickHouse database backed by
`MaterializedPostgreSQL`, consuming the Postgres WAL via logical
replication. `materialized_postgresql_schema_list` lets one CH
database carry both Postgres schemas — CH 25.x doesn't expose
`publication_name`, so two CH databases against the same Postgres
DB collide on the auto-named publication.

Cluster state after `cdc_setup.sql + cdc_bridge.sql`:

```
oltp_cdc   ops_dxb.customers  ReplacingMergeTree
oltp_cdc   ops_dxb.orders     ReplacingMergeTree
oltp_cdc   ops_msk.customers  ReplacingMergeTree
oltp_cdc   ops_msk.orders     ReplacingMergeTree
```

(The schema name is part of the CH table name and quoted with
backticks because of the dot:
`SELECT ... FROM oltp_cdc.\`ops_msk.customers\` FINAL`.)

Live E2E test — INSERT in Postgres → no manual refresh → SELECT in
ClickHouse within seconds:

```bash
# Postgres side
psql> INSERT INTO ops_msk.customers (customer_id, first_name, last_name)
        VALUES ('CDC-V2-MSK', 'NewMsk', 'CDC');
psql> UPDATE ops_msk.customers SET last_name='UPDATED'
        WHERE customer_id='CDC-V2-MSK';

# ClickHouse side, ~5s later (no INSERT INTO ... SELECT on CH at all)
clickhouse> SELECT customer_id, first_name, last_name
              FROM oltp_cdc.`ops_msk.customers` FINAL
              WHERE customer_id LIKE 'CDC-V2-%';

┌─customer_id─┬─first_name─┬─last_name─┐
│ CDC-V2-MSK  │ NewMsk     │ UPDATED   │
└─────────────┴────────────┴───────────┘
```

Row count parity vs source-of-truth Postgres:

```
   ┌─t───────────┬─count()─┐
1. │ msk_c_FINAL │      57 │
2. │ dxb_c_FINAL │      24 │
   └─────────────┴─────────┘
   ─ vs ─
 branch | pg_count
--------+----------
 msk    |    57
 dxb    |    24
```

After `promote_to_raw_vault_cdc.sql` re-runs against the CDC tables
(reading with `FINAL` to dedupe ReplacingMergeTree versions), the
pg_ops rows land in raw_vault and propagate to the BV order canonical
view:

```
   ┌─record_source─┬─count()─┐
1. │ pg_ops__dxb   │      24 │
2. │ pg_ops__msk   │      57 │
   └───────────────┴─────────┘
```

The `record_source = pg_ops__*` convention is identical to the
pull-based variant, so any downstream consumer (BV view / dbt mart /
cold-offload) sees the CDC path the same way it saw the
`oltp_live`-based promotion.
