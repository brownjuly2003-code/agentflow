# DV2 Supplier / Product Reference

A reproducible small-kitchen-appliance **reference** (suppliers, products, GS1
marking codes, product→supplier sourcing) for the AgentFlow DV2 raw vault —
the own-brand importer legend in [`docs/domain.md`](../../../../docs/domain.md),
pinned to exact numbers in [`docs/generator-spec.md`](../../../../docs/generator-spec.md).
It fills the catalog / `tnved_code` / GS1-marking slots that the transactional
feeds leave empty, and is the project's genuine **cloud** component: the
dataset is published to a Hugging Face Dataset — real object storage, not a
checkbox.

It is a *reference* (master/dimension) feed, distinct from the `1c` / `wms` /
`wb` transactional sources. Provenance is explicit: every row carries
`record_source = 'ref__global'` and lands in source-segregated
`*__ref__global` satellites.

## What is genuine vs. synthetic

Kept deliberately honest — the value is in real storage + real standards
conformance, not in pretending the identities are real.

**Genuine (verifiable, pinned by tests):**
- ТН ВЭД ЕАЭС headings — real 4-digit HS-aligned customs headings (8516/8509/
  8423/8422) with descriptions close to the official Russian wording
  (`tnved.py`).
- GS1 **GTIN-13** and **GLN-13** check digits — published GS1 mod-10
  algorithm (`gs1.py`).
- **RU INN-10** control digit — real algorithm for RU legal-entity tax ids.
- EAEU GS1 prefix range **460–469** — correct for this reference even though
  manufacturing is contracted to China: GTINs belong to the RU brand owner
  registered with GS1 RUS, regardless of where the goods are made.
- `gross_weight_g >= net_weight_g` packaging invariant.
- Pricing-ladder ordering per SKU: FOB < landed < wholesale < marketplace-net
  < RRC (generator-spec.md §5) — guaranteed by disjoint percentage bands.
- MD5 hash keys computed with the **same canonicalisation as the
  transactional loader**, so reference hubs/links join byte-for-byte with
  vault data already loaded from other sources (pinned in
  `tests/unit/test_dv2_supplier_reference.py`).

**Synthetic but labelled:**
- supplier legal names — **no brand token** anywhere in product data
  (own-brand importer decision, generator-spec.md §3);
- CN USCC-18 tax ids — structurally shaped per GB 32100-2015, but the check
  character is a labelled placeholder, not a verified mod-31 check digit
  (`make_cn_uscc18`);
- the specific SKU ↔ GTIN ↔ supplier assignments;
- packaging dimensions, RRC and FOB purchase prices;
- GPC brick codes (illustrative);
- ТН ВЭД sub-position digits — the genuine heading is zero-padded to the
  10-digit field (`<heading>000000`), i.e. heading granularity, **not** a
  fabricated precise commodity sub-position.

## DV2 raw-vault mapping

`vault_mapping.map_reference` lands the reference on shared hubs/links and its
own reference satellites:

| Reference entity | Hub | Link | Satellite (`ref__global`) |
|---|---|---|---|
| Supplier | `hub_supplier` | — | `sat_supplier_profile__ref__global` |
| Product | `hub_product` | — | `sat_product_reference__ref__global` (catalog + packaging + `tnved_code`) |
| GS1 marking | `hub_marking_code` | `lnk_product_marking` | `sat_marking_code_gs1__ref__global` |
| Sourcing | — | `lnk_product_supplier` | `sat_lnk_product_supplier__ref__global` |

The satellite DDL is generated the house way — from `spec.yaml` via
`generate_satellites.py` — so it stays consistent with the rest of the vault.

## Build the artifact

```bash
# from warehouse/agentflow/dv2
python -m reference.build --load-ts 2026-06-26T12:00:00Z
```

Outputs under `reference/build/` (git-ignored):
- `dataset/{suppliers,products,sourcing}.parquet` — the Hugging Face Dataset
  payload;
- `vault/<table>.parquet` — the same reference mapped to raw-vault rows, ready
  to land in the `rv` database;
- `manifest.json` — counts, seed, and the genuine-vs-synthetic ledger, so the
  dataset is self-describing on the Hub.

Determinism: a given `--seed` reproduces the dataset exactly. `--dry-run`
summarises counts without writing.

## Load into the PostgreSQL raw vault

The reference is storage-neutral, so the same mapping lands directly in the
PostgreSQL vault (`dv2/postgres/`) — no Parquet round-trip needed. Apply the
vault DDL first (`dv2/postgres/apply.sh`), then:

```bash
# from repo root, after dv2/postgres/apply.sh
python -m warehouse.agentflow.dv2.reference.load_postgres \
    --postgres-dsn postgresql://agentflow@localhost:5432/agentflow
```

Inserts are idempotent (`ON CONFLICT DO NOTHING`) and share the
`PostgresVaultWriter` with the X5 loader, so the reference and X5 feeds populate
the same vault without colliding. `--dry-run` maps and prints per-table counts
without connecting.

## Publish to the Hub (gated)

Publishing `dataset/` to `<hf-account>/agentflow-supplier-reference` is a
separate step performed with the Hub account token, e.g.:

```bash
huggingface-cli upload <hf-account>/agentflow-supplier-reference reference/build/dataset . --repo-type dataset
```

## Verify

```bash
# from repo root
SKIP_DOCKER_TESTS=1 python -m pytest tests/unit/test_dv2_supplier_reference.py -q
```
