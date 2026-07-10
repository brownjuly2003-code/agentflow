# S13 — at-scale proof on the project's own generator (2026-07-11)

> Stand: `deproject-mac` (Colima vz 6 GiB / 4 CPU, macOS 13.7.8 Intel),
> ClickHouse 24.8 in Docker, code `s13-scale-own-data @ 2075a6a`.
> Harness: `scripts/benchmark_scale_own_data.py --days 1460 --query-repeats 5`
> (CI runs the same harness at `--days 2` in the live-ClickHouse integration
> job — `tests/integration/test_scale_own_data_smoke.py`).

**What this proves.** The kitchen-appliance importer legend
([generator-spec.md](../generator-spec.md)) scaled to **4 years of history —
51.2 M rows, 2.87 M orders, 10.66 M per-unit Chestny Znak codes — entirely
from the project's own deterministic generator**, on the real checked-in
raw-vault DDL (ReplacingMergeTree hubs/links, MergeTree satellites, no
tuning). At that volume the §12 legend invariants still hold to the decimal
(channel mixes, AOV bimodality, branch shares, status flow, full-scan GS1
mod-10 validation of every GTIN), and analyst-shaped queries answer in
20–730 ms.

**What this does not claim.** Generation is in-database
(`INSERT … SELECT FROM numbers()`), so 845 k rows/s measures the generator +
ClickHouse write path on this host, not streaming ingestion (the streaming
path's numbers live in [throughput-realpath-q14-2026-07-10.md](throughput-realpath-q14-2026-07-10.md)
and [soak-s11-2026-07-10.md](soak-s11-2026-07-10.md)). Single node, laptop-class
VM — do not compare across hardware. Customer-PII / loyalty / product-catalog
satellites stay demo-scale: the legend itself fixes them (500-dealer book,
160-SKU catalog). `lnk_order_product` shows 4.285 M active-part rows vs
4.318 M written — ReplacingMergeTree collapsing repeat (order, product) picks
within an order, which is the link table's correct semantics, not loss.


## Volume

- Orders: **2,868,900** (1460 days ≈ 4.0 years at 1,965/day)
- Per-unit marking codes: **10,658,000**
- Total rows: **51,240,793** · compressed on disk: **1.91 GB** (uncompressed 2.90 GB)

## Load (in-database generation)

| Table | Rows | Seconds | Rows/s |
|---|---:|---:|---:|
| hub_customer | 636,500 | 0.5 | 1,229,691 |
| hub_order | 2,868,900 | 2.9 | 977,194 |
| lnk_order_customer | 2,868,900 | 3.3 | 880,675 |
| lnk_order_store | 2,868,900 | 3.3 | 862,572 |
| lnk_order_product | 4,318,047 | 5.2 | 829,799 |
| sat_order_header__bitrix__msk | 2,737,500 | 2.6 | 1,065,457 |
| sat_order_pricing__1c__msk | 2,737,500 | 2.5 | 1,113,942 |
| sat_order_header__bitrix__spb | 51,100 | 0.0 | 1,092,034 |
| sat_order_pricing__1c__spb | 51,100 | 0.0 | 1,093,217 |
| sat_order_header__bitrix__ekb | 36,500 | 0.0 | 1,006,704 |
| sat_order_pricing__1c__ekb | 36,500 | 0.0 | 1,046,289 |
| sat_order_header__bitrix__dxb | 21,900 | 0.0 | 826,518 |
| sat_order_pricing__1c__dxb | 21,900 | 0.0 | 838,712 |
| sat_order_header__bitrix__ala | 21,900 | 0.0 | 810,957 |
| sat_order_pricing__1c__ala | 21,900 | 0.0 | 848,132 |
| hub_marking_code | 10,658,000 | 11.4 | 933,998 |
| sat_marking_code_gs1__1c__global | 10,658,000 | 15.2 | 701,814 |
| lnk_product_marking | 10,658,000 | 13.5 | 789,396 |
| **total** | **51,273,047** | **60.6** | **845,578** |

## Analyst-query latency (server-side elapsed)

| Query | Median s | Min s | Max s | Rows read | Result rows |
|---|---:|---:|---:|---:|---:|
| monthly_revenue_by_channel | 0.300 | 0.131 | 1.945 | 2,868,900 | 147 |
| aov_by_channel | 0.025 | 0.023 | 1.555 | 2,868,900 | 3 |
| sku_volume_ranking_marketplace | 0.728 | 0.558 | 2.196 | 7,154,047 | 160 |
| branch_revenue_shares | 0.021 | 0.018 | 0.030 | 2,868,900 | 5 |
| order_360_point_lookup | 0.047 | 0.045 | 0.126 | 4,457,179 | 1 |
| marking_status_distribution | 0.020 | 0.019 | 0.035 | 10,658,160 | 3 |

## Correctness at scale (generator-spec §12)

| Check | Verdict | Detail |
|---|---|---|
| rowcount:hub_order | PASS | expected 2,868,900, got 2,868,900 |
| rowcount:lnk_order_customer | PASS | expected 2,868,900, got 2,868,900 |
| rowcount:lnk_order_store | PASS | expected 2,868,900, got 2,868,900 |
| rowcount:hub_customer | PASS | expected 636,500, got 636,500 |
| rowcount:hub_product | PASS | expected 160, got 160 |
| rowcount:hub_store | PASS | expected 6, got 6 |
| rowcount:hub_marking_code | PASS | expected 10,658,160, got 10,658,160 |
| rowcount:lnk_product_marking | PASS | expected 10,658,160, got 10,658,160 |
| rowcount:sat_marking_code_gs1__1c__global | PASS | expected 10,658,160, got 10,658,160 |
| rowcount:order_header_sats | PASS | expected 2,868,900, got 2,868,900 |
| §12.2 order-count mix | PASS | mp 89.1% · b2b 8.1% · d2c 2.8% |
| §12.3 revenue mix | PASS | b2b 69.0% · mp 29.6% |
| §12.4 AOV bands + bimodality | PASS | b2b 54,902 ₽ · d2c 3,300 ₽ · marketplace 2,150 ₽ |
| §12.10 msk revenue share | PASS | msk 59.6% |
| status flow 8/10/12/62/8 | PASS | pending 8.0% · confirmed 10.0% · shipped 12.0% · delivered 62.0% · cancelled 8.0% |
| §12.7 GTIN validity (full scan) | PASS | 0 invalid of 10,658,160 |
| marking status 25/60/15 | PASS | issued 25.0% · in_circulation 60.0% · withdrawn 15.0% |

## Disk footprint by table

| Table | Rows | Compressed MB | Uncompressed MB |
|---|---:|---:|---:|
| hub_marking_code | 10,658,160 | 285.8 | 479.6 |
| lnk_product_marking | 10,658,160 | 405.0 | 607.5 |
| sat_marking_code_gs1__1c__global | 10,658,160 | 487.5 | 714.1 |
| lnk_order_product | 4,285,147 | 160.3 | 244.3 |
| lnk_order_store | 2,868,900 | 97.7 | 163.5 |
| hub_order | 2,868,900 | 65.6 | 127.3 |
| lnk_order_customer | 2,868,900 | 137.9 | 163.5 |
| sat_order_header__bitrix__msk | 2,737,500 | 117.9 | 161.5 |
| sat_order_pricing__1c__msk | 2,737,500 | 122.2 | 199.8 |
| hub_customer | 636,500 | 14.3 | 25.5 |
| sat_order_header__bitrix__spb | 51,100 | 2.3 | 3.0 |
| sat_order_pricing__1c__spb | 51,100 | 2.4 | 3.7 |
| sat_order_pricing__1c__ekb | 36,500 | 1.7 | 2.7 |
| sat_order_header__bitrix__ekb | 36,500 | 1.6 | 2.2 |
| sat_order_pricing__1c__dxb | 21,900 | 1.0 | 1.6 |
| sat_order_header__bitrix__ala | 21,900 | 1.0 | 1.3 |
| sat_order_pricing__1c__ala | 21,900 | 1.0 | 1.6 |
| sat_order_header__bitrix__dxb | 21,900 | 1.0 | 1.3 |
| hub_product | 160 | 0.0 | 0.0 |
| hub_store | 6 | 0.0 | 0.0 |

