# DV2.0 Multi-Branch — Live Demo Evidence

**Data sections (§4–8) re-captured 2026-07-03** on the current
kitchen-gadget legend (post-B1/B2/B3 seeds), against standalone stands, no
Docker:

- **ClickHouse** — `clickhouse server` 26.7.1.492 (single binary, WSL Ubuntu
  22.04). Vault built from the repo files verbatim: `__init.sql` → 8 hubs →
  8 links → 48 satellites → `synthetic_seed.sql` + `satellite_seed.sql` +
  `satellite_seed_all_branches.sql` → `business_vault/*.sql` (views with
  `SQL SECURITY DEFINER`) → `governance/01..04.sql`.
- **PostgreSQL** — 17.5 (EDB windows-x64 binaries, `initdb` + `pg_ctl`, port
  55432, trust auth, user/db `agentflow`). Vault built via `postgres/apply.sh`
  (schema → 8 hubs → 8 links → 48 satellites → `03_business_vault.sql`) →
  `postgres/governance/01..04.sql`.

> **Legend reset (2026-07-03).** The demo no longer models a bulk-retail
> contractor built on a public benchmark dataset. It is an own-brand
> ("private-label smart-kitchen") importer: China-manufactured goods, RU HQ,
> bimodal channel economy (money in wholesale, order-count on marketplaces),
> five branches across three jurisdictions (msk / spb / ekb + dxb + ala). All
> prior at-scale order-count / USD figures are retired. The synthetic demo
> seed is now **2,500 customers / 10,000 orders / 160 SKU / 14,853 line
> items, priced in ₽** — see `docs/domain.md` and `docs/generator-spec.md`
> for the model.
>
> **⚠ `demo_voiced.mp4` / `demo.cast` are superseded.** Both were captured
> 2026-05-23, before this legend reset, and still show the retired
> fashion-retailer narration and the old 40/25/15/10/10 branch split.
> `demo_voiced.narration.txt` and `demo_transcript.txt` (the scripts behind
> them) were rewritten to the current legend in the G2 S5 follow-up PR; the
> `.mp4`/`.cast` media itself is pending re-recording on the Mac kind stand
> (plan step S6) — see `demo.cast.README.md` for detail.

> **Infra sections are being re-captured 2026-07-06 on the Mac kind stand.**
> The `hq-demo` kind cluster (Colima `vz` VM, kind v0.27.0 / k8s v1.32.2) was
> rebuilt and the DV2 stack redeployed on the current kitchen-legend seed
> (10,000 orders). §1–3 (topology / workload pinning / PVCs) now carry live
> output from this stand. §9–15 (MinIO cold tier, the Postgres→ClickHouse
> bridge, MaterializedPostgreSQL CDC, Argo orchestration, dbt marts) each carry
> their own capture status inline. The standalone WSL-CH / Windows-PG split used
> for §4–8 cannot reproduce cross-engine networking or Kubernetes, which is why
> these needed the kind cluster.

## Governance verify_live — both engines green on the new seeds

The adversarial PII-governance matrices (`governance/verify_live.sh` on
ClickHouse, `postgres/governance/verify_live.sh` on PostgreSQL) were re-run
against the freshly-built stands:

| Stand | Result | Transcript |
| ----- | ------ | ---------- |
| ClickHouse 26.7.1.492 | **29/29 PASS**, 0 FAIL, 0 WARN | [`../perf/vault-pii-governance-verify-2026-07-03.md`](../perf/vault-pii-governance-verify-2026-07-03.md) |
| PostgreSQL 17.5 | **33/33 PASS**, 0 FAIL, 0 WARN | [`../perf/vault-pii-governance-pg-verify-2026-07-03.md`](../perf/vault-pii-governance-pg-verify-2026-07-03.md) |

The PII boundary holds in every SQL shape on both engines; row policies scope
officers to their own jurisdiction; the msk demo seed now spans `1c__msk`,
`pg_ops__msk` and `mp__msk` record sources (the legacy marketplace-seed
prefix was retired in B2). The current CH suite defines 29 probes (earlier
revisions cited 32);
the count is whatever the checked-in script asserts — every probe passes.

## 1. Cluster topology — `kubectl get nodes --show-labels`

> **Re-captured 2026-07-06** on the Mac kind stand (Colima `vz` VM, kind
> v0.27.0, `kindest/node` v1.32.2). Three-node topology from
> `infrastructure/dv2/kind-hq-demo.yaml`, labels verbatim from the config.

```
NAME                    STATUS   ROLES           AGE   VERSION
hq-demo-control-plane   Ready    control-plane   14m   v1.32.2
hq-demo-worker          Ready    <none>          14m   v1.32.2
hq-demo-worker2         Ready    <none>          14m   v1.32.2
```

Labels decoded:

| Node                    | branch | nodepool         | workload    |
| ----------------------- | ------ | ---------------- | ----------- |
| hq-demo-control-plane   | msk    | hq-control       | —           |
| hq-demo-worker          | msk    | hq-data-tier-a   | postgres    |
| hq-demo-worker2         | msk    | hq-data-tier-b   | clickhouse  |

## 2. Workload pinning — `kubectl get pods -n dv2 -o custom-columns=POD,NODE`

> **Re-captured 2026-07-06** on the Mac kind stand. `nodeSelector` places each
> StatefulSet on its labelled node.

```
POD            NODE              STATUS
clickhouse-0   hq-demo-worker2   Running
postgres-0     hq-demo-worker    Running
```

`nodeSelector: workload=clickhouse|postgres` on each StatefulSet enforces the
placement — the same primitive that production would use to pin per-branch
edge nodes (`branch=dxb`, `branch=ala`).

## 3. Persistent storage — `kubectl get pvc -n dv2`

> **Re-captured 2026-07-06** on the Mac kind stand. Both `volumeClaimTemplates`
> bound against the kind `standard` (rancher local-path) StorageClass.

```
NAME                STATUS   CAPACITY   ACCESS MODES   STORAGECLASS
data-clickhouse-0   Bound    5Gi        RWO            standard
data-postgres-0     Bound    2Gi        RWO            standard
```

## 4. DV2.0 model surface — `system.tables` grouped by family

70 tables in database `rv` (`clickhouse client -q "SELECT ... FROM
system.tables WHERE database='rv'"`):

```
hub_*    8   (customer, product, order, shipment, store, supplier, employee, marking_code)
lnk_*    8   (order_customer, order_product, order_store, order_employee,
              order_shipment, shipment_store, product_supplier, product_marking)
sat_*   48   (per-source × per-branch satellites; full matrix in spec.yaml)
```

The satellite matrix grew from the earlier 22 to **48** across the B1 rewrite
(per-jurisdiction personal / loyalty / order-header / pricing / marketplace
sources; full generation in `spec.yaml` + `generate_satellites.py`).

## 5. Multi-branch distribution proof

The retired at-scale seed spread orders 40/25/15/10/10 across branches. The current
legend does **not** — every marketplace and e-com order is fulfilled from the
msk hub (`mp__` is msk-only), and branch identity lives in the dealer / B2B /
PII layers, not in the marketplace order stream. Order distribution by
`record_source`:

```sql
SELECT record_source, count() AS orders,
       round(count() * 100.0 / (SELECT count() FROM rv.hub_order), 1) AS pct
FROM rv.hub_order GROUP BY record_source ORDER BY orders DESC;
```

```
┌─record_source─┬─orders─┬──pct─┐
│ mp__msk       │   8900 │ 89.0 │
│ bitrix__msk   │    360 │  3.6 │
│ site__msk     │    280 │  2.8 │
│ bitrix__spb   │    180 │  1.8 │
│ bitrix__ekb   │    130 │  1.3 │
│ bitrix__ala   │     75 │  0.8 │
│ bitrix__dxb   │     75 │  0.8 │
└───────────────┴────────┴──────┘
```

Collapsed to branch (`splitByString('__', record_source)[2]`): **msk 9,540
(95.4%)**, spb 180, ekb 130, dxb 75, ala 75 — a total of **10,000 orders**.
The msk dominance is the legend, not a bug: marketplace + D2C is centrally
fulfilled, so the branch story is carried by the B2B dealer orders
(`bitrix__<branch>` = 820 rows) and the per-jurisdiction customer/PII split
(§8), not by the order-count histogram.

## 6. Multi-branch aggregation latency (demo scale)

`clickhouse client --time -q "SELECT splitByString('__', record_source)[2] AS
branch, count() FROM rv.hub_order GROUP BY branch ORDER BY 2 DESC"`:

```
0.015 s   (10,000 hub_order rows, per-row splitByString, 2-vCPU WSL)
```

This is the **demo-scale synthetic seed** (10k orders), not a load benchmark.
The multi-million-row throughput characterisation is a separate artifact
([`load-test-baseline.md`](load-test-baseline.md)) and is not part of the
synthetic demo evidence; the earlier multi-million-row latency capture is
retired with the 2026-07-03 legend reset.

## 7. Line items reach

```sql
SELECT count() FROM rv.lnk_order_product;  -- 14853
```

**14,853 line items across 10,000 orders (~1.49 per order)** — the bimodal
basket profile: marketplace and D2C orders are predominantly single-item,
while the B2B dealer orders carry multi-line baskets, pulling the mean just
above 1. `hub_product` holds **160 SKU**; `hub_marking_code` holds **12,160**
Chestny ZNAK marking codes — **160** SKU-level GTIN templates + **12,000**
per-unit codes (issued / in-circulation / withdrawn).

## 8. Business Vault — populated views with MDM conflict resolution

`bv_customer_mdm__<branch>` merges PII from 1C with loyalty from Bitrix
(LEFT JOIN — customers without a Bitrix profile stay visible with
`loyalty_source = NULL`). Per-branch shape
(`count()`, `email != ''`, `loyalty_segment != ''`):

```
branch  rows  with_pii  with_loyalty
msk     2190      2190           152    (2,000 retail + 190 dealers)
spb      100       100            80    (dealers only)
ekb       70        70            56    (dealers only)
dxb       60        60             0    (dealers only — no loyalty by design)
ala       80        80             0    (dealers only — no loyalty by design)
```

Total **2,500 customers**. The legend puts **all retail under the msk legal
entity** (regions carry only dealer accounts), so msk holds 2,190 of the 2,500
customers. Loyalty (a dealer retro-bonus program, not a consumer points
scheme) runs only in msk / spb / ekb; dxb (UAE) and ala (KZ) dealers have a
contract, not a bonus — hence `with_loyalty = 0` there, by design. msk loyalty
tiers: **core 38 / mid 76 / tail 38** (152 total ≈ 80% of the 190 msk
dealers).

`bv_order_canonical` joins Bitrix header + 1C pricing (+ Wildberries state
for the msk marketplace) across every branch:

```
branch  orders  with_header  with_pricing
msk       9540         9540          9540
spb        180          180           180
ekb        130          130           130
dxb         75           75            75
ala         75           75            75
```

All 10,000 orders resolve a header and pricing. The jurisdiction-specific tax
rates fall straight out of the per-branch 1C pricing satellites — one BI query
exercises the entire multi-branch model:

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

Sample ALA B2B rows (₽, wholesale-scale tickets — the money end of the
bimodal economy):

```
branch  channel  order_status  total_amount  header_source       pricing_source
ala     b2b      delivered            45890   bitrix__ala         1c__ala
ala     b2b      cancelled            49816   bitrix__ala         1c__ala
ala     b2b      delivered            48004   bitrix__ala         1c__ala
```

`bv_customer_mdm__dxb` returns dxb rows with Gulf-style faux PII, all tagged
`pii=1c__dxb`; the msk view never returns them — the per-branch view + RBAC
primitive enforces jurisdictional isolation (proven exhaustively by the
verify_live matrix above).

## 9. Cold-offload pipeline — MinIO S3 backed

> **Re-captured 2026-07-06** on the Mac kind stand (kitchen-legend seed). MinIO
> `minio-0` (StatefulSet + Service + `cold-tier` bucket) and the ClickHouse
> `s3()` offload ran on the live cluster; row counts below are current.

`infrastructure/dv2/minio.yaml` provisions a single-node MinIO
StatefulSet + Service + bucket-init Job. The cold-offload CronJobs
(`infrastructure/dv2/cold-offload-cronjob.yaml` + `cold-offload-fanout.yaml`)
write parquet straight into the `cold-tier` bucket via ClickHouse's native
`s3()` table function — no intermediate PVC, no `mc cp` step. A schema grep for
`first_name|last_name|email|phone|birth_date|pii_flag` on the exported files
returns 0 — the data-sovereignty contract is enforced by source selection
(`sat_customer_anon__1c__{branch}` is the only satellite the CronJob reads).

The five per-branch offloads (`INSERT INTO FUNCTION s3(...)` → `cold-tier`,
each verified by an `s3()` read-back) landed one partitioned parquet object per
branch. Listing straight from MinIO (`SELECT _path, count() FROM
s3('http://minio:9000/cold-tier/**/*.parquet', …)`):

```
cold-tier/branch=ala/year=2026/month=07/customers_anon.parquet     80
cold-tier/branch=dxb/year=2026/month=07/customers_anon.parquet     60
cold-tier/branch=ekb/year=2026/month=07/customers_anon.parquet     70
cold-tier/branch=msk/year=2026/month=07/customers_anon.parquet   2190
cold-tier/branch=spb/year=2026/month=07/customers_anon.parquet    100
```

2,500 anonymized customer rows across the five branches (msk 2,190 / spb 100 /
ekb 70 / dxb 60 / ala 80 — the §8 MDM population). `DESCRIBE` on the exported
parquet confirms the PII-free contract at the schema level — the six columns
are exactly the anon projection, with **0** of the PII names present:

```
customer_hk_hex   Nullable(String)
age_bucket        Nullable(String)
geo_region        Nullable(String)
customer_segment  Nullable(String)
load_ts           Nullable(DateTime64(3,'UTC'))
record_source     Nullable(String)
```

### Production swap path

The CronJob takes `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` from env
vars — point them at a real S3 / GCS / Yandex Object Storage and the `s3()`
function works unchanged; the `Secret/minio-creds` resource drops out and the
cloud-provider secret takes its place.

## 10. Hot tier — Postgres OLTP + ClickHouse `PostgreSQL()` bridge

> **Re-captured 2026-07-06** on the Mac kind stand (kitchen-legend seed,
> current customer/order names — no `Dasha/Egor/Fedor`-style retired fixture
> data). ClickHouse and Postgres share the `hq-demo` cluster network, so the
> live `PostgreSQL()` read-through actually crosses pods for real.

`warehouse/agentflow/dv2/postgres_oltp/seed.sql` populates Postgres with
`ops_msk` + `ops_dxb` schemas; `bridge.sql` creates
`oltp_live.{msk,dxb}_{customers,orders}` tables in ClickHouse using
`Engine = PostgreSQL(...)` — live read-through of the OLTP tables, no
replication slot required. `promote_to_raw_vault.sql` runs the hot → warm
step, landing `record_source = pg_ops__*` rows in `rv.hub_order` that surface
in `bv_order_canonical` with correct branch attribution.

Seed landed 50 msk customers + 200 msk orders, 20 dxb customers + 80 dxb
orders; the live `oltp_live.*` read-through returned the identical counts
(50/200/20/80) straight from Postgres via the `PostgreSQL()` engine. After
`promote_to_raw_vault.sql`, `rv.hub_order FINAL` / `rv.hub_customer FINAL`
show exactly `pg_ops__msk 200` / `pg_ops__dxb 80` and `pg_ops__msk 50` /
`pg_ops__dxb 20` — the `ReplacingMergeTree(load_ts)` idempotency the
architecture doc promises held in practice: this session's promotion script
was invoked twice (the first run's client connection dropped from transport
flakiness on this shared, CPU-contended Mac before confirming completion, so
it was re-run to be safe) and `FINAL` collapsed the raw duplicate rows back
to the exact expected counts, not double. A sample landed row:

```
order_bk          branch  channel  total_amount  header_source
OLTP-DXB-000001   dxb     b2b            60355   bitrix__dxb
```

confirming the `pg_ops__*`-sourced order resolves branch, channel, amount and
`header_source = bitrix__<branch>` through `bv_order_canonical` exactly like
every other source in the vault.

## 11. How to re-run

**Standalone data sections (§4–8), no Docker:**

```bash
# ClickHouse (WSL): single binary + repo DDL/seeds, then
clickhouse client --user default --password demo --database rv

# PostgreSQL (Windows/EDB): initdb + pg_ctl on :55432, then
PSQL="psql -h 127.0.0.1 -p 55432 -U agentflow -d agentflow" bash postgres/apply.sh

# Governance matrices:
CH_CLIENT="clickhouse client --config-file=client.xml" bash governance/verify_live.sh
PSQL="psql -h 127.0.0.1 -p 55432 -U agentflow -d agentflow" SEED_DEMO=1 \
    bash postgres/governance/verify_live.sh
```

(For CH 26.7+, put `default`/`demo` in a client `--config-file` rather than on
the command line — the verify script appends `--user <probe>`, and the engine
now rejects a duplicate `--user` flag.)

**Kind-cluster sections (§1–3, §9, §12–15):**

```bash
bash infrastructure/dv2/bootstrap.sh   # idempotent rebuild on the kind cluster
```

## 12. Argo Workflows orchestration

> ⚠ **Kind-cluster section — pending Mac re-capture.** Timings/counts below are
> retired-seed-era. DAG ordering (hub → link → satellite → cold-offload) is enforced by
> dependencies, not clock-time; that property is legend-independent.

`infrastructure/dv2/argo/` deploys Argo Workflows plus a `dv2-refresh`
WorkflowTemplate that chains hot → warm → cold as one DAG:

```
promote-oltp → validate-hubs → {validate-links, validate-satellites}
             → cold-offload (fan-out: msk, spb, ekb, dxb, ala) → verify-mirrors
```

A failure in `validate-links` aborts the run before any S3 write, so mirrors
are never out of sync with the warm tier.

## 13. dbt mart layer

> **Re-captured 2026-07-06** on the Mac kind stand, with one honest deviation
> from `infrastructure/dv2/dbt/dbt-run-job.yaml`: the `dbt-run-marts` Job (which
> `pip install`s `dbt-core`/`dbt-clickhouse` inside a fresh pod) triggered a host
> OOM on this memory-constrained shared Mac earlier in this session (5 parallel
> cold-offload Job pods, then a heavy view recompute, each needed a full kind
> node restart to recover — the host has ~600 MB–1 GB free with the DV2 stack
> plus another project's containers already running). Rather than retry a
> similarly heavy pod, the three mart **model SQL files themselves**
> (`warehouse/agentflow/dv2/dbt/models/marts/*.sql`) were compiled by stripping
> only the pure-templating Jinja (`{{ config(...) }}`, `{{ source('rv', X) }}`
> → `rv.X`) — no logic changes — and run directly as `CREATE TABLE ... AS
> SELECT` against the live `bv_order_canonical_mat` (also freshly rebuilt this
> session from the live `bv_order_canonical` view, with frugal per-query memory
> settings). The 12 `schema.yml` assertions (`not_null` / `accepted_values`)
> were then run as their equivalent raw SQL. This is not a `dbt run && dbt
> test` invocation, but every number below is genuine live output from the
> current kitchen-legend seed, not fabricated.

`warehouse/agentflow/dv2/dbt/` ships three materialized marts and 12 data
tests on top of the business vault, run via a Kubernetes Job
(`infrastructure/dv2/dbt/dbt-run-job.yaml`). `customer_360` populates one row
per `(customer_hk, branch)`; `branch_pnl.effective_tax_rate` validates the
per-jurisdiction wiring end-to-end (1C pricing satellites → BV view → dbt
mart) — the same 12/5/20% rates verified live in §8.

Row counts: `customer_360` 2,500 (one per customer — matches the §8
population), `branch_pnl` 5 (one per branch, single-month seed),
`returns_velocity` 14 (branch × channel × week grain). `branch_pnl` per
branch:

```
branch  orders  gross_revenue  effective_tax_rate
msk       9540       38792056                 0.2
spb        180        9366120                 0.2
ekb        130        6749619                 0.2
dxb         75        6737025                0.05
ala         75        3370575                0.12
```

10,000 total orders across the 5 `branch_pnl` rows; `effective_tax_rate`
reproduces the §8 jurisdiction rates exactly (RU 20%, UAE 5%, KZ 12%)
end-to-end through the mart layer. All **12/12** schema tests pass (0 failing
rows each): `customer_360` hk/branch not-null + branch `accepted_values` +
`return_rate` not-null; `branch_pnl` branch not-null + `accepted_values` +
month not-null; `returns_velocity` branch not-null + `accepted_values` +
channel not-null + week not-null + `return_rate` not-null.

## 14. Push-based CDC via MaterializedPostgreSQL

> ⚠ **Kind-cluster section — pending Mac re-capture.** MaterializedPostgreSQL
> consumes the Postgres WAL via logical replication and needs both engines on
> one network with `wal_level=logical`; the standalone split cannot reproduce
> it. Contents are retired-seed-era.

The pull-based `oltp_live` bridge is replaced by a single `oltp_cdc`
ClickHouse database backed by `MaterializedPostgreSQL`, consuming the Postgres
WAL. `materialized_postgresql_schema_list` lets one CH database carry both
Postgres schemas. Live E2E: an INSERT/UPDATE in Postgres surfaces in
ClickHouse within seconds with no manual refresh; `promote_to_raw_vault_cdc.sql`
(reading `FINAL` to dedupe ReplacingMergeTree versions) lands the `pg_ops__*`
rows in raw_vault.

## 15. Per-branch CDC fan-out

> ⚠ **Kind-cluster section — pending Mac re-capture.** Contents are retired-seed-era.

Operational reality wants a single branch to be pausable, re-snapshotable and
rotatable without touching another branch's stream. ClickHouse 25.5+ rejects a
custom publication name on `MaterializedPostgreSQL`, so the fan-out pattern
splits the source — one Postgres **database** per branch (`ops_msk_db`,
`ops_dxb_db`), each with its own auto-named publication and slot, consumed by
two independent CH `MaterializedPostgreSQL` databases (`oltp_cdc_msk`,
`oltp_cdc_dxb`). Isolation check: the msk CH database has zero rows from dxb.
