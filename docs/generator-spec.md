# Generator Spec — Unit Economics and Data Generation

Companion to [`domain.md`](domain.md) (the business legend). That document
fixes the frame — company, channels, footprint, seasonality; this one pins the
**numbers and distributions** every seed and generator must reproduce, and the
invariants that keep them mutually consistent. When a seed value and this spec
disagree, this spec wins.

Consumers, in execution order:

1. **Generator & seeds rebuild** — `warehouse/agentflow/dv2/reference/`
   (generator.py, tnved.py; gs1.py is unchanged), `synthetic_seed.sql`,
   `satellite_seed*.sql`, `postgres_oltp/seed.sql`. Faux-PII mechanics are
   preserved (§8).
2. **Record-source rename** — retired external-dataset prefix → `mp__*` (see domain.md §5.4).
3. **Serving demo repin** — the four demo tables, NL demo answers, `ORD-*`
   values (§9).
4. **Evidence regeneration** — demo_evidence and live-verify counts re-pinned
   on the new seeds.

---

## 1. Master matrix — baseline day

All money **net of VAT, in ₽** — every branch is seeded in ₽; the pinned demo
FX constants of §10 are documentation-only. "Baseline day" = seasonal
multiplier 1.0; the seasonal calendar (§4) modulates it and averages to
exactly 1.0 over the year.

| Channel | Branch | Orders/day | Avg check, ₽ | Revenue, ₽/day |
| ------- | ------ | ---------: | -----------: | -------------: |
| B2B wholesale | `msk` | 70 | 52,000 | 3,640,000 |
| B2B wholesale | `spb` | 35 | 52,000 | 1,820,000 |
| B2B wholesale | `ekb` | 25 | 52,000 | 1,300,000 |
| B2B re-export (Gulf) | `dxb` | 15 | 90,000 | 1,350,000 |
| B2B / EAEU | `ala` | 15 | 45,000 | 675,000 |
| Marketplace FBS (WB ~60% / Ozon ~40%) | `msk` | 1,750 | 2,150 | 3,762,500 |
| Own D2C site | `msk` | 55 | 3,300 | 181,500 |
| **Total** | | **1,965** | | **12,729,000** |

Roll-ups that follow (and must keep following) from this table:

- **Annual revenue** ≈ 12.729M × 365 ≈ **4.65 B ₽** — inside the 3–5 B ₽
  legend corridor.
- **Revenue mix**: B2B 69.0% · marketplaces 29.6% · D2C 1.4%.
- **Order-count mix**: marketplaces 89.1% · B2B 8.1% · D2C 2.8%.
- **Branch revenue**: msk 59.6% · spb 14.3% · dxb 10.6% · ekb 10.2% ·
  ala 5.3%.
- **Branch order count**: msk ≈ 95.4% (it fulfils all e-com), the rest is
  regional B2B. This asymmetry is deliberate: branch diversity in the vault
  lives in **customers, PII, loyalty, shipments and B2B orders**, not in
  marketplace order volume.

The old seed's 40/25/15/10/10 branch distribution of *orders* does not
survive the legend: all FBS/D2C fulfils from the msk central warehouse, so the
consolidated marketplace feed (`mp__*`) is msk-only. 40/25/15/10/10-style
spreads remain valid only for the **dealer book** (§7).

## 2. Order shapes

| Channel | Lines/order | Units/line | Notes |
| ------- | ----------- | ---------- | ----- |
| B2B RU | 3–10 (avg ~6) | 4–24 (avg ~5.5) | ≈ 33 units/order at wholesale prices; deferred payment flag; retro-bonus accrual 3% |
| B2B dxb | 4–12 | 8–48 | export pallets; ≈ 56 units/order |
| B2B ala | 3–8 | 4–24 | ≈ 28 units/order |
| Marketplace FBS | 1 (95%), 2 (5%) | 1 | single-item retail; 3% cancel/return allowance |
| D2C site | 1–3 (avg 1.3) | 1–2 | gift orders skew to 2+ lines in peak weeks |

Status flow everywhere = the serving contract's
`pending → confirmed → shipped → delivered / cancelled`. Steady-state status
distribution for a seeded snapshot: delivered 62%, shipped 12%, confirmed 10%,
pending 8%, cancelled 8% (marketplace cancels dominate the last bucket).

## 3. SKU catalog — 160 SKUs, 10 categories

Retail prices are RRC (recommended retail), ₽, `x,x90`-style endings.
ТН ВЭД at real 4-digit heading granularity, 10-digit form zero-padded —
the established honesty convention of `tnved.py` is preserved.

| # | Category (RU source systems) | EN slug (serving) | SKUs | RRC band, ₽ | HS/ТН ВЭД heading |
| - | ---------------------------- | ----------------- | ---: | ----------- | ----------------- |
| 1 | Электрочайники | kettles | 22 | 1,490–3,990 | 8516 |
| 2 | Аэрогрили и грили | grills | 20 | 3,490–7,990 | 8516 |
| 3 | Блендеры | blenders | 20 | 1,690–4,490 | 8509 |
| 4 | Миксеры (вкл. планетарные) | mixers | 14 | 1,990–7,990 | 8509 |
| 5 | Кофеварки и кофемолки | coffee | 18 | 1,990–6,990 | 8516 |
| 6 | Мультипекари, вафельницы, сэндвичницы | multibakers | 16 | 1,790–3,490 | 8516 |
| 7 | Измельчители (чопперы) | choppers | 12 | 1,290–2,490 | 8509 |
| 8 | Соковыжималки | juicers | 10 | 2,490–5,990 | 8509 |
| 9 | Кухонные весы | scales | 12 | 790–1,490 | 8423 |
| 10 | Вакууматоры и сушилки | vacuum-dry | 16 | 2,290–5,490 | 8422 (вакууматоры) / 8516 (сушилки) |

- **Volume skew (ABC)**: top 24 SKUs ≈ 55% of marketplace unit volume,
  next 56 ≈ 35%, tail 80 ≈ 10%. Bestsellers concentrate in categories
  1, 3, 6, 7, 9 — exactly the 1.5–3k ₽ marketplace-check zone.
- **Naming — no brand token (decision).** The importer is deliberately
  unnamed (domain.md §1), so product names carry **no brand string** —
  eliminates any trademark-collision risk and nothing in the pipeline needs
  one. Names are built from category + attributes:
  RU (1С side): «Чайник электрический 1,7 л, 2200 Вт»;
  EN (serving side): "Electric Kettle 1.7L 2200W".
  Attribute pools per category (volume, power, bowl count, wattage…) are the
  generator implementer's choice; names must stay deterministic per seed.
- **RU vs EN split (decision):** DV2/warehouse content is RU-flavored (that is
  what 1С/Битрикс emit); the serving demo store and NL-queried catalog stay EN
  (that is the product-team surface the docs and SDKs speak). One SKU id maps
  both.
- **SKU id shapes stay as-is** to minimize churn: reference catalog `RC%06d`
  (`RC000001…RC000160`), DV2/serving seeds `SKU-#####`. Only the count
  changes: **800 → 160** products (expect seed-count test pins to move).

## 4. Seasonal calendar

Two monthly-multiplier curves, each averaging exactly 1.0. The **B2B curve
leads the retail curve by ~1 month** — dealers stock up ahead of consumer
peaks; that lead-lag is the shape analysts should be able to *find* in the
data.

| Month | Retail (MP + D2C) | B2B (all branches) | Why |
| ----- | ----------------: | -----------------: | --- |
| Jan | 0.70 | 0.60 | post-NY trough |
| Feb | 1.10 | 1.15 | Feb 23 retail; dealers stock for Mar 8 |
| Mar | 1.20 | 0.95 | Mar 8 gift peak |
| Apr | 0.85 | 0.85 | |
| May | 0.80 | 0.80 | |
| Jun | 0.75 | 0.85 | low season |
| Jul | 0.80 | 0.95 | first NY containers ordered |
| Aug | 0.90 | 1.05 | |
| Sep | 0.95 | 1.20 | dealer NY stocking starts |
| Oct | 1.05 | 1.40 | peak dealer stocking |
| Nov | 1.45 | 1.30 | 11.11; late dealer top-ups |
| Dec | 1.45 | 0.90 | consumer NY peak; too late to restock B2B |

Day-level spikes on top of the retail curve: **Nov 11** ×2.5 (marketplace
sale), **Dec 10–25** ramp to ×1.6, **Mar 1–7** ×1.8, **Feb 14–22** ×1.25.
Supply echo: containers land 40–60 days after FOB (§6) — procurement for the
December peak is committed by early October.

## 5. Pricing ladder and unit economics

Per-SKU price ladder, expressed as a share of RRC. Every SKU must satisfy the
chain **FOB < landed < wholesale < marketplace-net < RRC**:

| Rung | Share of RRC | Meaning |
| ---- | -----------: | ------- |
| FOB purchase price (CNY, converted) | 24–30% | contract factory price |
| Landed cost | 32–40% | FOB + sea freight + duty + Chestny ZNAK marking + inbound handling |
| Wholesale (B2B price list) | 60–65% | dealer price before retro-bonus |
| Marketplace net proceeds | ≈ 78% | RRC − commission (~17%) − FBS logistics (~135 ₽) − returns allowance (3%) |
| RRC | 100% | own site price = RRC |

Per-average-order contribution (baseline, net of VAT):

| Channel | Avg check, ₽ | Main deductions | Contribution, ₽ | Margin |
| ------- | -----------: | --------------- | --------------: | -----: |
| Marketplace FBS | 2,150 | commission 366 · FBS 135 · returns 65 · marking/pack 18 · landed 774 | ≈ 790 | ~37% |
| B2B RU | 52,000 | landed 30,190 · retro-bonus 1,560 · delivery/credit 800 | ≈ 19,450 | ~37% |
| B2B dxb | 90,000 | export pricing is thinner | ≈ 18,000 | ~20% |
| B2B ala | 45,000 | | ≈ 13,500 | ~30% |
| D2C site | 3,300 | acquiring 66 · delivery 250 · marketing ~400 · landed 1,188 | ≈ 1,400 | ~42% |

Sanity roll-up: annual contribution ≈ 1.6 B ₽ (~35% of revenue) — a healthy
mid-size importer; nothing in the data should contradict this order of
magnitude.

## 6. Suppliers and sourcing (reference generator)

The reference was originally grocery-shaped (dairy/bakery supplier stems,
food brands, gram weights, food ТН ВЭД headings); it has since been replaced
wholesale with the kitchen-appliance reference specified below (see CHANGELOG
for the swap):

- **30 suppliers**: 22 CN contract factories (Guangdong/Zhejiang-style names,
  e.g. "Foshan …", "Ningbo …", "Cixi … Electric Appliance Co., Ltd." —
  synthetic and labelled as such, per the generator's honesty convention),
  5 RU (packaging, manuals, cords/components), 2 AE (JAFZA trading
  consolidators — the dxb re-export leg), 1 KZ (local services distributor).
  `COUNTRY_WEIGHTS` → `(("CN", 72), ("RU", 16), ("AE", 8), ("KZ", 4))`.
- **Tax-id shapes**: RU INN-10 keeps its real check digit (implemented);
  CN = 18-char USCC — implement the real GB 32100-2015 check character if
  cheap, otherwise a labelled structural placeholder (document which, keep the
  genuine-vs-synthetic note accurate); AE TRN 15 digits and KZ BIN 12 digits
  stay as today.
- **Sourcing**: 1–2 suppliers per SKU (primary + backup), MOQ 300–1,000
  units, `lead_time_days` 40–60 (sea) with ~10% of rows at 12–18 (air),
  quarterly `valid_from` repricing. Purchase prices follow the §5 ladder.
- **GS1 stays exactly as-is** (`gs1.py` untouched): the EAEU prefix range
  460–469 is *correct* for an own-brand importer — GTINs belong to the RU
  brand owner registered with GS1 RUS, regardless of where manufacturing
  happens. The module docstring already records this rationale.
- **`tnved.py`**: the former grocery headings were replaced by the four
  appliance headings of §3 (8516, 8509, 8423, 8422) with RU descriptions
  close to official wording, heading-granularity honesty note preserved.

## 7. Customer populations

**Dealer book (B2B) — 500 active accounts:**

| Branch | Accounts | Note |
| ------ | -------: | ---- |
| msk | 190 | incl. federal chains' central offices |
| spb | 100 | |
| ekb | 70 | Urals/Siberia dealers |
| dxb | 60 | Gulf wholesale buyers |
| ala | 80 | KZ + EAEU neighbours |

Ordering frequency: 200 core accounts ≈ 4 orders/week (regional chains place
per-outlet restocks), 200 mid ≈ 1.5/week, 100 tail ≈ 0.5/week →
**≈ 164 B2B orders/day**, consistent with §1. Each account carries 1–3
decision-maker contacts in Bitrix24 (≈ 900 contact persons) with birth dates —
the gift-campaign trigger.

**Retail identities:** ~150k marketplace buyer ids (12% repeat within 90
days) and ~9k D2C accounts (35% repeat). Retail customers belong to the msk
legal entity (it runs all RU e-com), so their PII lives in `*__msk`
satellites; regional branches hold **dealer** customers only.

## 8. Faux-PII mechanics — preserved

The existing mechanics carry over verbatim (only populations/semantics
change): deterministic name arrays per jurisdiction, `@example.test` /
`@example.kz` emails, city phone prefixes (+7495/+7812/+7343 RU, +7727 KZ,
+971 AE), birth-date spreads, `hash_diff` idempotency, `customer_hk =
MD5(number)` linkage across hubs/satellites. New requirements:

- dxb satellites use AE-appropriate names/phones (+971, latin transliteration)
  — dealer contacts there are Gulf trading companies' buyers;
- dealer contacts (the ~900) must populate `birth_date` densely — campaigns
  query it; retail birth dates may stay sparse (~40% filled);
- loyalty satellites (`sat_customer_loyalty__bitrix__*`) now mean **dealer
  retro-bonus state**: `loyalty_segment` ∈ {core, mid, tail},
  `loyalty_points` = accrued quarterly bonus in ₽ (3% of quarter's purchases,
  resets quarterly), `last_visit_at` = last order date. Only dealer customers
  get loyalty rows; msk/spb/ekb only (as today — dxb/ala dealers are on
  contract terms, not the bonus program).

## 9. Serving demo store (repin targets)

The four demo tables keep their shapes and row counts; values move to the
legend. Targets:

- **`products_current` (10 rows)**: representative SKUs across §3 categories,
  EN names, EN category slugs, RUB prices from the RRC bands,
  `stock_quantity` = central-warehouse shared pool; exactly **one
  out-of-stock bestseller** stays in the seed — the oversell/freshness story
  needs it.
- **`orders_v2` (8 rows)**: bimodality must be visible even in 8 rows —
  5 marketplace-scale orders (1,500–3,000 ₽), 1 D2C (~4,000 ₽), 2 wholesale
  (≈ 48,000 and ≈ 76,000 ₽). `currency = 'RUB'` everywhere (branch currencies
  live in the vault, not the serving demo). `ORD-YYYYMMDD-NNNN` format and
  the relative-`NOW()` timestamps stay.
- **`users_enriched` (5 rows)**: 2 dealer contacts (lifetime spend ~1.2M and
  ~460k ₽, `preferred_category` from §3 slugs) + 3 retail buyers (3–40k ₽).
- **`sessions_aggregated` (6 rows)**: unchanged mechanics — D2C-site-only
  telemetry per the legend; funnel stages as today.
- NL demo answers, README curl examples, and any pinned revenue/count values
  are recomputed from the new rows (that is the demo-repin step's whole job);
  `avg_order_value` demos should showcase the bimodality (segment before
  averaging — domain.md §5.1).

## 10. Currencies and determinism

- **All seeded amounts in the main vault seeds are ₽, in every branch.**
  `synthetic_seed.sql` and `postgres_oltp/seed.sql` (the seeds that back the
  vault/serving demo and §1's rates) store only the ₽ figures — no generator
  or seed in that path performs an FX conversion at runtime, and cross-branch
  aggregates there work directly in ₽. In the legend narrative dxb invoices
  in AED and ala in KZT, but nothing in the main seed path materializes that.
  **Exception: `postgres_oltp/fanout/02_seed.sql`.** This is a separate,
  intentional CDC/multi-currency replication fixture (the per-branch
  Postgres→ClickHouse fan-out demo) — it seeds `orders.currency` as the local
  tag per branch (msk = RUB, dxb = AED) on purpose, to prove the fan-out
  carries a real per-row currency column through CDC.
  `postgres_oltp/fanout/04_ch_bridge.sql` only replicates each branch's rows
  into its own ClickHouse database, preserving whatever currency tag was
  seeded — it never sums AED and RUB into one figure. The AED amounts there
  are converted to ₽ only in this doc's/that file's comments, for illustrative
  reference, using the FX constants below — never at runtime or in any
  aggregation query. The **pinned demo FX constants** (not live rates;
  internally consistent with a 90 ₽/USD world): `AED = 24.50 ₽`, `KZT = 0.175
  ₽`, `CNY = 12.40 ₽` — kept in `reference/legend.py` solely as the fixed
  conversion basis for any doc/evidence sentence that quotes a non-₽ figure
  (e.g. FOB in CNY, or the fanout fixture's AED totals). If a future revision
  stores branch-local currencies in the main seed path, these are the
  constants it must use.
- Generator seed constant stays `20260626`; everything derives
  deterministically from it. Timestamps keep today's mechanics (relative
  `NOW()` in serving demo, `load_ts = now64()` in vault seeds).

## 11. DV2 seed volumes

Target row counts for the rebuilt `synthetic_seed.sql` + satellites
(≈ 5 baseline days of orders; old values in parentheses):

| Object | Target | Was |
| ------ | -----: | --- |
| `hub_store` | 6 store codes, unchanged | 6 |
| `hub_customer` | 2,500 = 500 dealers + 2,000 retail | 2,000 |
| `hub_product` | 160 | 800 |
| `hub_order` | 10,000 ≈ 5.1 baseline days: 8,900 mp + 280 site + 820 B2B (per-branch: msk 360, spb 180, ekb 130, dxb 75, ala 75 — §1 rates × 5.1, matches §7's ≈164/day) | 10,000 |
| `lnk_order_product` rows | ≈ 14,600 (§2 shapes: mp ~1.05 lines, site ~1.3, B2B ~6) | ~25,000 |
| `hub_marking_code` | 160 SKU GTINs + ~12,000 per-unit code sample (≈ one container), statuses issued 25 / in_circulation 60 / withdrawn 15 | per-product only |
| `hub_supplier` | 30 | 40 |

Order dates spread uniformly over a ~122-hour (≈ 5.1-day) window ending at
load time — 10,000 orders / 5.1 days ≈ **1,965 orders/day**, exactly §1's
baseline rate. Baseline days carry seasonal multiplier 1.0 by definition, so
§4's monthly curves are deliberately **not** encoded in this seed: a 5-day
snapshot cannot express a 12-month shape; the seasonality belongs to the
long-horizon generator narrative, not the vault seed.

Customer→branch and order→channel assignments follow §1/§7 proportions; the
`multiIf(number % 100 < …)` slicing technique stays, only the cut points
move. Order `record_source` reflects the channel: `mp__msk` (marketplace
feed), `site__msk`, `bitrix__<branch>` / `1c__<branch>` (B2B). The Postgres
OLTP hot-tier seed mirrors the same populations at smaller scale.

## 12. Consistency invariants

Machine-checkable assertions the generator rebuild must encode as tests —
this list is the definition of "цифры взаимно согласованы":

1. Annual revenue (Σ channels × 365 × seasonal avg 1.0) ∈ **[3.5, 5.0] B ₽**.
2. Order-count mix: marketplaces 88–90%, B2B 7–9%, D2C 2–4%.
3. Revenue mix: B2B 65–72% of ₽; marketplaces 27–33%.
4. Order-weighted avg B2B check (all B2B branches together) ∈ [30k, 80k] ₽ —
   §1 puts it at ≈ 54.9k. Per-branch B2B avg checks span 45k (ala) to 90k
   (dxb): the RU + EAEU wholesale channels each sit inside [30k, 80k], while
   dxb's 90k export-pallet check sits above that band **by design** (§1) and
   is not a violation. Avg marketplace check ∈ [1.5k, 3.0k] ₽. The AOV
   distribution is bimodal with no channel average between 10k and 25k.
5. Per SKU: FOB < landed < wholesale < marketplace-net < RRC (§5 ladder).
6. Each seasonal curve's 12 multipliers average exactly 1.0.
7. Every GTIN passes `is_valid_gtin13`, prefix ∈ 460–469 — both the
   reference-catalog GTINs (minted via `gs1.make_gtin13`) and the vault
   seed's `gs1_gtin` literals in `synthetic_seed.sql`, whose check digits are
   precomputed with the same GS1 mod-10 algorithm and pinned by the invariant
   tests.
8. Every `tnved_code` is one of the §3 headings, 10-digit zero-padded form.
9. Dealer accounts × ordering frequency ⇒ 150–200 B2B orders/day.
10. Branch revenue shares sum to 100%; msk ∈ [55%, 65%].
11. Faux-PII locale rules hold per jurisdiction (names / phone prefixes /
    email TLDs per §8); `hash_diff` idempotency and `customer_hk` linkage
    preserved.
12. Loyalty rows exist only for dealer customers in msk/spb/ekb;
    `loyalty_points` ≤ 3% of that dealer's trailing-quarter purchases.

## 13. Out of scope (v1)

- **IoT / device telemetry** — narrative only, never in data (domain.md §1).
- **Inbound container receipts as shipment rows** — the container storyline
  stays in `excel__*` manifests; a structured inbound leg on `hub_shipment`
  is an operational-layer roadmap item, not a seed requirement.
- **KZ marketplace (Kaspi) channel for ala** — ala stays B2B/EAEU wholesale
  in v1.
- **Company-level P&L** (OPEX, payroll) — unit economics stop at
  per-order contribution (§5).
