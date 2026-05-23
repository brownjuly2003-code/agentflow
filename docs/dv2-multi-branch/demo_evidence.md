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

## 10. How to re-run on the same cluster

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
