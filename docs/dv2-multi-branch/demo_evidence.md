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

`bv_order_canonical`:

```
branch  orders  with_header  with_pricing
msk      4000   4000         4000
spb      2500      0            0
ekb      1500      0            0
dxb      1000      0            0
ala      1000      0            0
```

MSK joins Bitrix header + 1C pricing for every row. The other branches keep
hub-level order rows visible with NULL header / pricing — analysts see "we
have the order, we don't yet have the source data" instead of a silent drop.
Sample:

```
msk  retail       paid       8902   subtotal=8902   tax=1780.4   header=bitrix__msk  pricing=1c__msk
msk  call-center  paid      25327   subtotal=25327  tax=5065.4   header=bitrix__msk  pricing=1c__msk
msk  call-center  delivered 14091   subtotal=14091  tax=2818.2   header=bitrix__msk  pricing=1c__msk
```

## 9. Cold-offload pipeline — end-to-end run

`kubectl apply -f infrastructure/dv2/cold-offload-cronjob.yaml` provisioned
a 1 Gi `cold-exports` PVC plus a CronJob scheduled at `0 2 * * *` MSK-local.
A manual run (`kubectl create job --from=cronjob/dv2-cold-offload-msk
cold-offload-manual-...`) finished `Complete 1/1` in 2m14s — first-time
image pull dominated; subsequent runs reuse the cached `clickhouse-server:25.5`.

Output landed at
`/exports/branch=msk/year=2026/month=05/customers_anon.parquet` (20 411 B,
800 rows). `clickhouse-local DESCRIBE TABLE file(...)` confirms the shape:

```
customer_hk_hex   Nullable(String)
age_bucket        Nullable(String)
geo_region        Nullable(String)
customer_segment  Nullable(String)
load_ts           Nullable(DateTime64(3, 'UTC'))
record_source     Nullable(String)
```

Sample (verbatim from the parquet via `clickhouse-local`):

```
00AC8ED3B4327BDD4EBBEBCB2BA10A00 | 18-24 | msk-center | churned | 2026-05-23 05:45:46.197 | 1c__msk
01161AAA0B6D1345DD8FE4E481144D84 | 25-34 | msk-south  | vip     | 2026-05-23 05:45:46.197 | 1c__msk
013A006F03DBC5392EFFEB8F18FDA755 | 45-54 | msk-center | regular | 2026-05-23 05:45:46.197 | 1c__msk
```

A grep of the parquet schema for `first_name|last_name|email|phone|birth_date|pii_flag`
returns 0 — the data-sovereignty contract from `architecture.md` is enforced
by source (`sat_customer_anon__*` is the only satellite the CronJob reads).

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
