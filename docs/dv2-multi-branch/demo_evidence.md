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

## 8. How to re-run on the same cluster

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
