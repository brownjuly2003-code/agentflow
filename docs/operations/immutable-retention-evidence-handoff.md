# Immutable Retention Evidence Handoff

## Status

Status as of 2026-05-06: blocked on external immutable-retention evidence if
the project needs claims beyond the local hash-chained audit export.

The repository can write hash-chained JSONL audit records through
`AGENTFLOW_AUDIT_LOG_PATH`. That is useful local tamper-evidence, but it is not
proof of WORM retention, object-lock policy, SIEM retention, or a separate
compliance-controlled audit store.

Evidence recheck on 2026-05-06 found no S3 Object Lock bucket, immutable backup
vault, SIEM retention export, Kafka-to-WORM sink, retention-policy artifact,
storage owner, access-control proof, or restore/readback evidence supplied to
the repo.

## Required Evidence Record

Do not claim external immutable retention until every field below is supplied by
the storage owner or compliance operator.

| Field | Required value |
|-------|----------------|
| Storage owner | Team/person accountable for the immutable store |
| Retention target | S3 Object Lock, immutable backup vault, SIEM, or equivalent |
| Retention mode | Governance/compliance mode or equivalent immutability control |
| Retention period | Duration and policy name/version |
| Audit source | Source stream/file/table and export mechanism |
| Access controls | Owner-approved writer, reader, and delete/retention administrators |
| Policy evidence | Redacted policy export, CLI output, console export, or ticket |
| Write evidence | Dated sample export path, object version, or sink delivery proof |
| Readback evidence | Query, object metadata, restore, or retrieval proof |
| Review owner | Person approving customer-facing retention claims |

## Acceptable Artifact Links Or Paths

- Redacted S3 Object Lock bucket policy or retention-rule export.
- SIEM or log-archive retention-policy export with policy name and date.
- Kafka Connect, Firehose, or equivalent sink evidence showing audit records
  delivered to the immutable target.
- Object metadata or retention readback proving the retention mode and retain
  until date.
- Secure evidence-folder or ticket link that keeps account IDs, private
  hostnames, and customer data out of the repository.

## No-Go Conditions

Keep this item blocked if any condition is true:

- The only evidence is local hash-chained JSONL, DuckDB analytics, tests, or
  documentation.
- Retention policy is described verbally without a dated artifact.
- The storage target allows the application writer to delete or shorten
  retention.
- Evidence exposes secrets, account material, private hostnames, or customer
  data in the repository.
- The retention claim exceeds the configured target, source, or retention
  period.

## Boundary

Local hash-chain verification can support tamper-evidence during development.
External immutable retention requires a separate storage control and operator
evidence outside this repository.
