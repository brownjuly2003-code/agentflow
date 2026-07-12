# AgentFlow Disaster Recovery Runbook

## Scope

**This runbook covers local DuckDB file backup/restore only** — the primary
pipeline DuckDB, the API usage/auth DuckDB, and the non-secret parts of
`config/`. It is the DR story for the embedded, single-host demo profile.

It does **not** cover, and nothing in this repository currently implements:

- **ClickHouse** (the external serving backend, ADR 0006/0007): no backup,
  snapshot, or restore path exists for it. Losing the ClickHouse node loses
  its data.
- **PostgreSQL control plane** (ADR 0009/0010): no PITR, base backup, or WAL
  archiving exists for it. Losing the Postgres instance loses webhook, alert,
  outbox and usage-accounting state.
- A restore ever executed against a real deployed (staging or production)
  environment. Everything below has only been exercised against synthetic
  fixtures created on an ephemeral GitHub Actions runner — see
  [Nightly Automation](#nightly-automation).

If you are running the ClickHouse or PostgreSQL profile, treat this document
as "the embedded/demo path is covered, the scale profile is not." Building
real ClickHouse/PostgreSQL backup and running a staging restore drill is
still open work (audit `P1-2`, program stage "DR and production security").

## Recovery Objectives

**No number in this section is a validated production SLA.** The previous
version of this runbook stated a flat RPO of 24 hours and an RTO of 15-30
minutes as if they had been measured against a deployed environment; they
had not been, so they are removed. What is actually true today:

- `scripts/backup.py` writes `rpo_achieved_seconds` into every archive's
  `manifest.json`: the gap between the backup timestamp and the newest
  DuckDB file's last-modified time *at backup time*. That number is real and
  mechanically computed, but it describes the fixture the regression
  workflow builds, not a production system's write lag. `CHECKPOINT` runs
  synchronously before copying, so it measures "time since last checkpoint,"
  not "time since last write" — a busy database can still lose whatever
  happened between its last checkpoint and the moment it actually failed.
  `--rpo-target-seconds` (default 86400) only controls what the manifest
  *flags* as stale; it is not an SLA anyone has committed to.
- Restore duration has never been timed against a real host-loss scenario.
  RTO is undefined until a restore drill runs against a staging environment
  and someone records the wall-clock time (see
  [Testing and Drills](#testing-and-drills)).
- For ClickHouse and PostgreSQL: RPO/RTO are effectively unbounded today —
  a lost node loses everything since whatever was last exported by hand,
  because no automated backup exists for either store.

## Backup Coverage

Every backup archive contains:

- The primary DuckDB file (`DUCKDB_PATH`, default `agentflow_demo.duckdb`)
- The API usage DuckDB file (`AGENTFLOW_USAGE_DB_PATH`, default
  `agentflow_api.duckdb`)
- Any remaining DuckDB WAL files after checkpointing
- Everything under `config/` **except**:
  - `config/api_keys.yaml` — bcrypt key hashes and HMAC lookup digests
  - `config/webhooks.yaml` — webhook signing secrets
  - `config/tenants.yaml` — tenant routing/quota definitions
- `manifest.json` with SHA-256 checksums for every archived file

**The three excluded files are credential/routing material, not
disaster-recovery data.** `scripts/backup.py` filters them out using the same
`scripts/check_release_artifacts.FORBIDDEN_MEMBER_PATTERNS` the Python
release-artifact check already enforces on the sdist and wheel, so they never
leave the host inside a tar archive, a 7-day GitHub Actions artifact, or (if
you pass `--output s3://...`) an S3 object. `tests/unit/test_backup.py`
regression-tests the exclusion.

If you lose them, they are **not** recoverable from a backup archive — that
is the point. Recover them like this instead:

- `config/api_keys.yaml`: issue new keys against the running API
  (`scripts/rotate_key.py`, which calls the admin key-rotation endpoint) —
  do not try to restore old hashes.
- `config/webhooks.yaml`: re-register webhooks; in any profile beyond local
  demo, the signing secret should come from your secret manager, not a file
  on disk.
- `config/tenants.yaml`: re-apply from your own source of truth. This repo
  keeps a demo `config/tenants.yaml` in git, so `git checkout` (or your
  GitOps flow) recovers the demo version.

On Helm, none of the three ever exist as plain files on the pod's filesystem
in the first place — they are mounted from a Kubernetes `Secret` at
`/etc/agentflow/secret` (`helm/agentflow/templates/deployment.yaml`), never
baked into the image or written to `config/` on disk.

## Backup Procedure

Create a local backup:

```bash
python scripts/backup.py --output /tmp/agentflow-backups/
```

The command:

1. Runs `CHECKPOINT` on each DuckDB database before copying.
2. Copies the active DuckDB files and the non-secret parts of `config/`.
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
   - checks that tenant schemas from `config/tenants.yaml` exist in the
     primary DuckDB file, **if** a `config/tenants.yaml` is already present
     at `--target-root` — since the archive no longer carries that file, a
     restore into a fresh, empty `--target-root` (the drill scenario below)
     skips this particular check rather than failing on it

Restoring `config/api_keys.yaml`, `config/webhooks.yaml` or
`config/tenants.yaml` is out of scope for `scripts/restore.py` by the same
policy that keeps them out of the archive — see
[Backup Coverage](#backup-coverage) for how to recover each one.

## Failure Scenarios

### DuckDB corruption

Symptoms:
- `duckdb` cannot open the file
- API health checks fail because serving tables are unreadable

Response:
1. Stop writes to the affected instance.
2. Run `python scripts/verify_backup.py <backup.tar.gz>`.
3. Run `python scripts/restore.py --backup <backup.tar.gz>`.
4. Start the API and confirm `GET /health/ready` returns a healthy status.

### Config loss

Symptoms:
- Missing `config/serving.yaml`, `config/slo.yaml`, `config/security.yaml`,
  contract files, or (separately) `config/api_keys.yaml` /
  `config/webhooks.yaml` / `config/tenants.yaml`
- Authentication or tenant routing fails after restart

Response:
1. For anything other than the three excluded files: restore the archive
   with `python scripts/restore.py --backup <backup.tar.gz>`.
2. For `config/api_keys.yaml`, `config/webhooks.yaml`, or
   `config/tenants.yaml`: the backup archive does not have them — recover
   each one using the steps under [Backup Coverage](#backup-coverage).
3. Confirm the restored `config/` matches the expected environment
   overrides.
4. Reload or restart the API process.

### Full server loss

Symptoms:
- Host is unavailable
- Local disk is gone

Response:
1. Provision a replacement host or volume.
2. Download the latest verified backup archive from remote storage or
   workflow artifacts.
3. Extract it with `python scripts/restore.py --backup <backup.tar.gz>
   --target-root <new-root>`.
4. Re-apply deployment-specific environment variables and secrets,
   including `config/api_keys.yaml`, `config/webhooks.yaml` and
   `config/tenants.yaml` (not part of the archive — see
   [Backup Coverage](#backup-coverage)).
5. Start the API and validate `/health/ready`.
6. If the lost host was running ClickHouse or the PostgreSQL control plane,
   note that this procedure does not recover either — see
   [Scope](#scope).

## Testing and Drills

- Verify every new archive with `python scripts/verify_backup.py backup.tar.gz`.
- Run a restore drill at least once per quarter into an isolated directory.
- Record the observed restore duration and compare it against an RTO target
  once one has actually been set (see
  [Recovery Objectives](#recovery-objectives) — none is committed to yet).
- Record the time gap between backup creation and the last durable write.
- **Not done yet:** every drill so far has run against synthetic fixtures on
  an ephemeral CI runner, never against a real staging environment. A
  staging restore drill with a measured RPO/RTO is open work, not a
  completed control.

## Nightly Automation

`.github/workflows/backup.yml` ("Backup/Restore Regression Test") runs
nightly at **02:00 UTC** and on manual dispatch. It does not touch a
deployed environment — it is a regression test for the backup/restore code
path, not a disaster-recovery control. The workflow:

1. Builds synthetic DuckDB fixtures on the runner.
2. Creates a timestamped backup archive from those fixtures.
3. Verifies the SHA-256 manifest.
4. Runs a restore smoke test into a temporary directory.
5. Uploads the resulting archive as a GitHub Actions artifact
   (`agentflow-backup-restore-regression-fixture`, 7-day retention).

A green run means `scripts/backup.py`, `scripts/verify_backup.py` and
`scripts/restore.py` still work together correctly. It does not mean a real
environment has been backed up or could be restored.
