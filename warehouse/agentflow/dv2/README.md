# AgentFlow DV2.0 Raw Vault

This directory contains the ClickHouse 24.x Raw Vault layer derived from `docs/dv2-multi-branch/schema_dv2.md`.

## Layout

- `raw_vault/hubs/`: eight hub DDL files.
- `raw_vault/links/`: eight link DDL files.
- `raw_vault/satellites_template.sql.j2`: Jinja2 template used by the generator.
- `raw_vault/satellites/`: generated satellite DDL files.
- `spec.yaml`: source x branch matrix and satellite definitions.
- `generate_satellites.py`: generator for satellite DDL.
- `business_vault/`: placeholder for future Business Vault objects.

## Generate Satellites

Run from this directory:

```bash
python generate_satellites.py --out-dir raw_vault/satellites
```

The generator reads `spec.yaml`, renders `raw_vault/satellites_template.sql.j2`, and writes one `.sql` file per satellite entry.

## Load Order

1. Execute `__init.sql` to recreate the `rv` database.
2. Execute all files from `raw_vault/hubs/`.
3. Execute all files from `raw_vault/links/`.
4. Execute generated files from `raw_vault/satellites/`.

All table files use `CREATE TABLE IF NOT EXISTS`. Hubs and links use `ReplacingMergeTree(load_ts)`. Satellites use `MergeTree`, `PARTITION BY toYYYYMM(load_ts)`, and `ORDER BY (hk, load_ts)`.
