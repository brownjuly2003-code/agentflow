# AgentFlow Disaster Recovery Runbook

## Scope

This runbook covers local DuckDB recovery for AgentFlow, including tenant-scoped schemas, API usage data, and the full `config/` directory.

## Recovery Objectives

- **RPO**: 24 hours by default. If the backup workflow runs hourly, effective RPO drops to 1 hour.
- **RTO**: under 15 minutes when restoring from local disk, under 30 minutes when restoring from remote storage.

## Backup Coverage

Every backup archive contains:

- The primary DuckDB file (`DUCKDB_PATH`, default `agentflow_demo.duckdb`)
- The API usage DuckDB file (`AGENTFLOW_USAGE_DB_PATH`, default `agentflow_api.duckdb`)
- Any remaining DuckDB WAL files after checkpointing
- The full `config/` directory, including:
  - `config/api_keys.yaml`
  - `config/tenants.yaml`
  - `config/contracts/`
  - `config/slo.yaml`
  - `config/pii_fields.yaml`
  - `config/security.yaml`
  - `config/webhooks.yaml`
- `manifest.json` with SHA-256 checksums for every archived file

## Backup Procedure

Create a local backup:

```bash
python scripts/backup.py --output /tmp/agentflow-backups/
```

The command:

1. Runs `CHECKPOINT` on each DuckDB database before copying.
2. Copies the active DuckDB files and `config/`.
3. Writes `manifest.json` with SHA-256 hashes and file sizes.
4. Packages the result as `agentflow-backup-<timestamp>.tar.gz`.

Validate the archive immediately after creation:

```bash
python scripts/verify_backup.py /tmp/agentflow-backups/agentflow-backup-YYYYMMDDTHHMMSSZ.tar.gz
```

## Restore Procedure

Restore into the current project root:

```bash
python scripts/restore.py --backup /tmp/agentflow-backups/agentflow-backup-YYYYMMDDTHHMMSSZ.tar.gz
```

Restore into an isolated directory for drill testing:

```bash
python scripts/restore.py \
  --backup /tmp/agentflow-backups/agentflow-backup-YYYYMMDDTHHMMSSZ.tar.gz \
  --target-root /tmp/agentflow-restore
```

The restore flow:

1. Extracts the archive into a temporary working directory.
2. Re-validates every file against `manifest.json`.
3. Restores files into `--target-root`.
4. Runs a smoke test:
   - opens each restored DuckDB file in read-only mode
   - confirms `api_usage` exists in the usage database
   - checks that tenant schemas from `config/tenants.yaml` exist in the primary DuckDB file

## Failure Scenarios

### DuckDB corruption

Symptoms:
- `duckdb` cannot open the file
- API health checks fail because serving tables are unreadable

Response:
1. Stop writes to the affected instance.
2. Run `python scripts/verify_backup.py <backup.tar.gz>`.
3. Run `python scripts/restore.py --backup <backup.tar.gz>`.
4. Start the API and confirm `GET /v1/health` returns a healthy status.

### Config loss

Symptoms:
- Missing `config/api_keys.yaml`, `config/tenants.yaml`, or contract files
- Authentication or tenant routing fails after restart

Response:
1. Restore the archive with `python scripts/restore.py --backup <backup.tar.gz>`.
2. Confirm the restored `config/` matches the expected environment overrides.
3. Reload or restart the API process.

### Full server loss

Symptoms:
- Host is unavailable
- Local disk is gone

Response:
1. Provision a replacement host or volume.
2. Download the latest verified backup archive from remote storage or workflow artifacts.
3. Extract it with `python scripts/restore.py --backup <backup.tar.gz> --target-root <new-root>`.
4. Re-apply deployment-specific environment variables and secrets.
5. Start the API and validate `/v1/health`.

## Testing and Drills

- Verify every new archive with `python scripts/verify_backup.py backup.tar.gz`.
- Run a restore drill at least once per quarter into an isolated directory.
- Record the observed restore duration and compare it against the RTO target.
- Record the time gap between backup creation and the last durable write to confirm the RPO target.

## Nightly Automation

`.github/workflows/backup.yml` runs a nightly backup at **02:00 UTC** and on manual dispatch. The workflow:

1. Creates a timestamped backup archive.
2. Verifies the SHA-256 manifest.
3. Runs a restore smoke test into a temporary directory.
4. Uploads the resulting archive as a GitHub Actions artifact.
