# Domain Model — the Business Behind the Demo Data

AgentFlow is the platform. This document describes the **company whose data
flows through it** in every seed, demo, metric, and warehouse table — the
single source of truth for the business legend. Docs, demo values, the data
generator, and the operational layer are aligned to this document, not the
other way around.

Downstream consumers:

- **Generator spec / unit economics** — order volumes, channel mix, and
  seasonality below are the fixed frame; exact distributions are pinned in
  [`generator-spec.md`](generator-spec.md).
- **Docs sweep** — README, `docs/architecture.md`, and the DV2 docs inherit
  the storyline and the vocabulary from §5.
- **Operational layer design** — the three ops surfaces (order timeline,
  stuck-orders worklist, exception inbox) serve the workflows in §4; the
  serving split is decided in
  [ADR 0011](decisions/0011-ops-serving-split.md) and the surface contracts
  are pinned in [`ops-surfaces-spec.md`](ops-surfaces-spec.md).

---

## 1. The company

A **mid-size Russian own-brand (private-label) importer of small kitchen
appliances**. Product design, QC, and the brand live in Russia; manufacturing
is contracted to audited factories in China. The archetype is well established
on the Russian market — own-brand appliance importers of this shape have grown
from ~4.7 to ~13–14 B ₽ of annual revenue over the last five years
([Forbes on the Kitfort founders](https://www.forbes.ru/svoi-biznes/533609-kak-prodavcy-bytovoj-tehniki-postroili-kompaniu-s-vyruckoj-bolee-14-mlrd-rublej)).
The demo company sits earlier on that curve: **~2,000 orders/day, ~3–5 B ₽/year**
— large enough for real multi-channel pain, small enough that a single data
platform team is plausible.

**Positioning.** Mid price segment with a deliberate value twist: the product
*looks* premium but sells at an accessible price (marketplace bestsellers at
1,500–3,000 ₽, top lines at 5,000–8,000 ₽). The catalog is small kitchen
appliances: kettles, grills and air fryers, blenders and planetary mixers,
coffee makers, multibakers, kitchen scales, vacuum sealers. A large share of
purchases are **gifts** — which drives both the seasonality (§3) and the CRM
practice of tracking contact birthdays for gift campaigns.

**Brand narrative vs. data.** The marketing story is "smart kitchen" —
app-connected appliances are part of the brand's roadmap and demo narrative,
but **no IoT/device telemetry exists in the v1 data model**. Do not add device
events, firmware versions, or app sessions to seeds or contracts; the data
story is orders, stock, and fulfilment.

**Brand name.** Deliberately unnamed in v1 ("the importer"). Product names in
seeds use neutral category-based names without a brand string — settled as a
hard decision in [`generator-spec.md`](generator-spec.md) §3: no brand token
anywhere in the data.

### Footprint: 5 locations, 3 jurisdictions

| Branch | Region | Jurisdiction | Role in the legend |
| ------ | ------ | ------------ | ------------------ |
| `msk`  | RU     | RU           | HQ, central warehouse (fulfils all three RU channels), main WMS |
| `spb`  | RU     | RU           | Regional warehouse + B2B showroom |
| `ekb`  | RU     | RU           | Regional warehouse (Urals/Siberia dealer logistics) |
| `dxb`  | UAE    | UAE          | **Re-export trading hub, registered as a free-zone entity in JAFZA (Jebel Ali Free Zone)**: China → Jebel Ali → Gulf market + re-export. Re-export is ~40% of UAE foreign trade; Chinese electronics reach the Middle East through exactly this route |
| `ala`  | KZ     | KZ           | **EAEU hub**: Kazakhstan local market + EAEU customs contour |

Each branch is a separate legal entity in its jurisdiction, which is why
per-jurisdiction PII satellites and per-branch row policies in the DV2 vault
are a business requirement, not an architectural flourish: RU customer data
stays in RU, UAE data in UAE, KZ data in KZ.

The `dxb` entity's free-zone registration is load-bearing for the economics:
goods held in JAFZA sit **outside UAE customs territory** (no import duty
until they enter the mainland, none at all on re-export), and qualifying
free-zone trading income is taxed at 0% under the UAE corporate tax regime.
That is what makes a China → Jebel Ali → Gulf/Africa consolidation-and-re-export
leg cheaper than routing the same containers through the mainland — and why
the branch exists as a trading hub rather than a sales office.

## 2. Channels and order shapes

Three sales channels with deliberately asymmetric economics — most of the
**money** is wholesale, most of the **order count** is marketplaces:

| Channel | Who buys | Order shape | Typical check | Volume |
| ------- | -------- | ----------- | ------------- | ------ |
| **B2B wholesale** | Several hundred active dealer accounts: regional appliance chains, gift/corporate buyers, independent e-com sellers | Multi-line orders (boxes of units), negotiated prices, deferred payment, retro-bonus program | 30,000–80,000 ₽ | ~150–200 orders/day |
| **Marketplaces (FBS)** | Retail buyers on Wildberries / Ozon | Single-item orders fulfilled from the importer's own warehouse (FBS) | 1,500–3,000 ₽ | ~1,800 orders/day |
| **Own D2C site** | Retail buyers, brand loyalists, gift shoppers | Small orders; the only channel with session/funnel telemetry | 2,000–5,000 ₽ | small share of orders |

Market grounding: in the small-appliance category ~76% of purchases happen
online and ~92% of online purchases go through marketplaces; category sales
grew ~50% on Wildberries and ~65% on Ozon in 2025
([Oborot.ru](https://oborot.ru/articles/rynok-bytovoj-tehniki-82-i271420.html),
[AdIndex](https://adindex.ru/news/researches/2026/05/26/345316.phtml)).
An importer with a 90/10 marketplace/D2C split in retail order count is the
norm, not an outlier.

Channel-specific mechanics that show up in the data:

- **Retro-bonuses (B2B).** Dealers earn quarterly rebates for hitting volume
  thresholds. This is what "loyalty" means in this business — dealer bonus
  accrual, not retail points.
- **CRM-driven B2B sales.** Wholesale runs on Bitrix24: deals, dealer
  organizations, and decision-maker contacts, including birthdays — the gift
  assortment makes personal dates a real sales trigger.
- **Marketplace mechanics (FBS).** Commission, returns with a return window,
  price promos dictated by platform sales events. Stock is *shared* with the
  other channels — see the oversell case in §4.

## 3. Seasonality and supply

- **Demand peaks are gift-driven**: New Year (Nov–Dec, the dominant peak),
  March 8, a secondary February 23 bump, plus marketplace-dictated sale events
  (11.11, platform birthdays).
- **Supply is containers from China**: 40–60 day lead time (factory → sea →
  customs → central warehouse). Procurement for the New Year peak is committed
  in early autumn; a late or customs-stuck container is a top-3 business risk
  and a core operational storyline (§4).
- **Regulatory frame — mandatory marking.** Russia's Chestny ZNAK (Честный
  знак) marking became **mandatory for importers of electronics on
  2026-05-01**, with the remaining household-appliance categories (multicookers,
  microwaves, vacuum cleaners, etc.) joining on 2026-09-01
  ([kontur.ru](https://kontur.ru/markirovka/spravka/53675-markirovka_radioelektronnoy_produkcii),
  [1C](https://torg.1c.ru/news/v-2026-godu-vsya-elektronika-dolzhna-byt-promarkirovana/)).
  For a kitchen-appliance importer in mid-2026 this is a live compliance
  program: every imported unit carries a GS1 DataMatrix code. This is why the
  warehouse has a first-class marking-code hub (`hub_marking_code`) and why
  customs classification (ТНВЭД) lives in the product catalog satellite.

## 4. Operational reality — what the ops surfaces serve

The operations team currently juggles five tools to answer one question about
one order: 1С, Bitrix24, the WMS screen, marketplace seller cabinets, and
logistics Excel sheets. AgentFlow's serving layer exists to replace that
tab-switching with one API surface. Three recurring situations define the
requirements:

1. **Cross-channel stock sync (the freshness case).** One central warehouse
   serves all three channels. A wholesale order for 200 units of a bestseller
   must be reflected in available-to-promise *before* the marketplaces keep
   selling those units — otherwise the importer ships apologies instead of
   goods and collects marketplace penalties for cancellations. This is the
   business reading of AgentFlow's headline **event → live metric** axis:
   second-level freshness is not a vanity benchmark, it is oversell
   prevention.
2. **The inbound container.** ETA / customs / receiving status for goods on
   the water. Everyone from procurement to B2B sales plans against it
   ("promise the dealer the grills from the March container?"). Today it lives
   in Excel manifests (`excel__*` sources); surfacing it is a roadmap item for
   the ops layer.
3. **Kill-the-five-programs triage.** Where is order X? Which orders are stuck
   between confirmation and shipment longer than the stage SLA? Which failed
   events need a manual decision? These map to the three ops surfaces —
   **Order 360 timeline**, **stuck-orders worklist**, and **exception inbox** —
   now live (`GET /v1/entity/order/{id}/timeline`, `/v1/ops/stuck-orders`,
   `/v1/ops/exceptions`).

## 5. Reinterpretation dictionary

Ground rule: **entity and table names in code do not change.** The legend is
applied by reading existing structures in domain terms (and by docs), not by
renames. The two exceptions are listed in §5.4.

### 5.1 Serving layer (demo store: 4 entities, 6 metrics)

| Code artifact | Reading in the legend |
| ------------- | --------------------- |
| `order` / `orders_v2` (`ORD-YYYYMMDD-NNNN`) | An order from **any** of the three channels. Status flow `pending → confirmed → shipped → delivered / cancelled` is the central-warehouse fulfilment path |
| `user` / `users_enriched` | A **customer**: either a dealer-account contact (B2B) or a retail buyer (D2C/marketplace). `total_spent` = lifetime value; `preferred_category` = appliance category |
| `session` / `sessions_aggregated` | **D2C site sessions only** — marketplaces do not expose session telemetry. Funnel stages (`add_to_cart`, `checkout`) are meaningful for the D2C slice |
| `product` / `products_current` | An own-brand SKU (kettle, air fryer, blender, …); `category` = small-appliance category; `stock_quantity` = units at the central warehouse — the shared pool behind the oversell case |
| metric `revenue` | Confirmed order value across **all channels** |
| metrics `order_count`, `avg_order_value` | All channels; AOV is bimodal by design (30–80k ₽ wholesale vs 1.5–3k ₽ retail) — segment before averaging |
| metrics `conversion_rate`, `active_sessions` | D2C site funnel only |
| metric `error_rate` | Pipeline/data health (an ops signal, not a commerce number) |

### 5.2 DV2 warehouse (hubs, satellites, business vault)

| Code artifact | Reading in the legend |
| ------------- | --------------------- |
| `hub_store` / `store_code` (`msk-01`, `spb-shr-02`, …) | A **branch facility**: central warehouse, regional warehouse, showroom, hub office. Not a retail chain store |
| `hub_customer` | Dealer organizations *and* retail buyers, deduplicated to one golden record; representations live in per-source satellites |
| `hub_supplier` (`supplier_inn` / foreign tax-id) | **Chinese contract factories** (plus a few RU packaging/component suppliers — hence INN support) |
| `hub_employee` | Sales / account managers — B2B attribution |
| `hub_marking_code` (`gs1_gtin`) | Chestny ZNAK GS1 DataMatrix codes — a live importer obligation since 2026-05-01 (§3) |
| `hub_shipment`, `lnk_order_shipment` | Outbound warehouse shipments (split-shipment capable). Inbound container receipts are the planned second leg of this hub |
| `sat_customer_loyalty__bitrix__*` | **Dealer retro-bonus program**: segment, accrued bonus (né "points"), last activity |
| `sat_customer_personal__1c__*` | Contact PII per jurisdiction; `birth_date` is load-bearing — gift campaigns run on contact birthdays |
| `sat_order_marketplace__wb__*` | FBS order facets: platform status, commission, return window |
| `sat_product_catalog__1c__*` (ТНВЭД) | Customs classification — first-class data for an importer, not decoration |
| `sat_product_stock__wms__*` | The shared stock pool (`qty_on_hand` / `qty_reserved` / `qty_available`) that all three channels draw down |
| `bv_customer_mdm` | Golden customer record: 1С is master for identity/PII, Bitrix24 for the commercial relationship |
| `bv_order_canonical` | One status vocabulary across channels — the substrate for Order 360 and stuck-orders |

### 5.3 `record_source` prefixes (source systems)

| Prefix | System | Feeds |
| ------ | ------ | ----- |
| `1c__` | 1С:УТ + 1С:ЗУП (ERP) | Orders, pricing, catalog, suppliers, employees, customer identity |
| `bitrix__` | Bitrix24 CRM | B2B deals, dealer orgs, decision-maker contacts, retro-bonus state |
| `wms__` | Warehouse management | Stock, shipments, marking codes at receiving |
| `site__` | Own D2C site | Sessions, behavior events, site orders |
| `wb__` | Wildberries seller API | FBS orders, commissions, returns |
| `excel__` | Logistics spreadsheets | Container manifests, cross-dock — the inbound-container storyline |
| `pg_ops__` | Postgres OLTP (hot tier) via CDC | Operational order/customer rows promoted into the vault |
| `mp__` | Consolidated marketplace order feed | High-volume retail order history |

### 5.4 Planned renames / repins (the only code changes the legend requires)

| Change | Scope | Status |
| ------ | ----- | ------ |
| `x5__*` → `mp__*` record_source (+ governance SQL, officer probes, admission tests) | The prefix carried the name of the Kaggle seed dataset (X5 Retail Hero) that the demo loader replays as transaction history. Under the legend it is the **consolidated marketplace feed**, and the prefix says so. Dataset attribution stays in the loader README | **Done** (B2) |
| Demo value repin: currencies to `RUB` (primary), `AED`/`KZT` in branch stories; demo revenue/counts consistent with §1–2 | `contracts/entities/order.yaml` currency examples, NL demo answers, seeded `ORD-*` rows | Planned (data phase, after the generator spec) |

Vocabulary guardrails for all public docs: the company is an **own-brand /
private-label importer** — always that framing; "store" (in `hub_store`) is
rendered as *branch/warehouse*, never as a retail shop; "loyalty" is rendered
as *dealer retro-bonuses*; IoT stays in the brand narrative and out of the
data model.

## 6. Personas × questions × endpoints

Six humans, one machine, one compliance role. Endpoints marked **planned** are
the operational-layer roadmap; everything else is live API surface.

| Persona | Questions they ask | Surface |
| ------- | ------------------ | ------- |
| **Owner / CEO** | "Revenue today vs yesterday? Orders during the НГ peak? Is AOV holding after the price move?" | `GET /v1/metrics/revenue` · `order_count` · `avg_order_value`; `POST /v1/query` (NL: "top products this week") |
| **B2B account manager** | "What has dealer X ordered this quarter? Are they on track for the retro-bonus threshold? Which of my contacts has a birthday before March 8?" | `GET /v1/entity/user/{id}`; `POST /v1/query`; vault: `bv_customer_mdm`, `sat_customer_loyalty__bitrix__*` |
| **E-com / marketplace manager** | "Site conversion this week? Are WB orders flowing or did the feed break? Top SKUs by orders during the sale event?" | `GET /v1/metrics/conversion_rate` · `active_sessions` · `error_rate`; `GET /v1/admin/analytics/top-entities` (admin-key); `POST /v1/query` |
| **Operations manager** | "Everything about ORD-20260404-1001 — now, in one place. Which orders are stuck pre-shipment past SLA? What failed overnight and needs a human?" | `GET /v1/entity/order/{id}`; `/v1/alerts` (+history/test); `/v1/deadletter` (+replay/dismiss); `GET /v1/entity/order/{id}/timeline`; `GET /v1/ops/stuck-orders`; `GET /v1/ops/exceptions` (+stats/acknowledge/resolve) |
| **Category / procurement manager** | "Which SKUs sell fastest per branch? What is on hand vs reserved? When does the next container land?" | `GET /v1/search`; `GET /v1/entity/product/{id}`; `POST /v1/query`; vault: `sat_product_stock__wms__*`; container ETA — **planned** (today: `excel__*` manifests) |
| **Data engineer / analyst** | "Which events move this metric? What is the contract and its staleness budget? What changed between contract v3 and v4? Are we inside SLO?" | `GET /v1/catalog`; `/v1/contracts/*` (+versions/diff/validate); `/v1/lineage/*`; `/v1/slo`; `/v1/admin/analytics/*` (admin-key) |
| **AI agent / integration** | Any of the above, programmatically — the agent is one consumer, not the product | Python/TS SDKs, MCP/LangChain/LlamaIndex integrations over the same API: `POST /v1/query` + `/v1/query/explain`, `/v1/entity/*`, `POST /v1/batch`, `/v1/webhooks`, `/v1/stream` |
| **PII officer (per jurisdiction)** | "Who can read dealer-contact PII in `dxb`? Prove RU data never crosses the border" | Not REST: DV2 governance — jurisdiction-scoped officer roles, column-limited analyst grants, per-branch row policies (`warehouse/agentflow/dv2/governance/`, ClickHouse and Postgres variants) |

The bimodal channel mix is what makes several of these questions interesting:
revenue questions need channel segmentation (§5.1), stock questions are
cross-channel by nature, and the operational questions exist precisely because
three channels share one warehouse.

## 7. Sources

Market research grounding the legend (retrieved 2026-07-03):

- [Forbes — история основателей Kitfort](https://www.forbes.ru/svoi-biznes/533609-kak-prodavcy-bytovoj-tehniki-postroili-kompaniu-s-vyruckoj-bolee-14-mlrd-rublej) — own-brand importer archetype and revenue trajectory
- [Oborot.ru — рынок бытовой техники](https://oborot.ru/articles/rynok-bytovoj-tehniki-82-i271420.html) — online/marketplace share in the small-appliance category
- [AdIndex — прогноз продаж бытовой техники](https://adindex.ru/news/researches/2026/05/26/345316.phtml) — category growth on WB/Ozon
- [Контур — маркировка радиоэлектроники](https://kontur.ru/markirovka/spravka/53675-markirovka_radioelektronnoy_produkcii) and [1С — сроки маркировки электроники](https://torg.1c.ru/news/v-2026-godu-vsya-elektronika-dolzhna-byt-promarkirovana/) — Chestny ZNAK timeline for importers
- [Кристалл Форвардинг — импорт через Jebel Ali](https://kf.com.ru/uae) and [DDA — торговые партнёры ОАЭ](https://dda-realestate.com/posts/torgovye-partnery-oae-import-eksport-mezdunarodnaia-torgovlia) — UAE re-export share and the China → Gulf electronics route
