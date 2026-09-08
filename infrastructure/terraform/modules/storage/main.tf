variable "environment" { type = string }
variable "lake_bucket_name" { type = string }
variable "noncurrent_version_expire_days" { type = number }

# Customer-managed key so key rotation, usage audit and revocation stay in
# project control instead of the AWS-managed aws/s3 key.
resource "aws_kms_key" "lake" {
  description         = "agentflow ${var.environment} lake bucket at-rest encryption"
  enable_key_rotation = true
}

resource "aws_kms_alias" "lake" {
  name          = "alias/agentflow-${var.environment}-lake"
  target_key_id = aws_kms_key.lake.key_id
}

resource "aws_s3_bucket" "lake" {
  bucket = var.lake_bucket_name
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.lake.arn
    }
    bucket_key_enabled = true
  }
}

# Nothing under `warehouse/` is on an S3 clock, and that is the whole rule.
#
# An Iceberg table is a set of manifests naming the data files a snapshot needs.
# A file's age says nothing about whether some live snapshot still points at it,
# so S3 expiration under the warehouse does not clean a table -- it makes the
# table unreadable. Two rules here deleted on age anyway (audit FB-11):
#
#   * "raw-data-lifecycle" -- GLACIER after 90 days and expiration after 365 on
#     prefix `warehouse/raw/`;
#   * "iceberg-metadata" -- expiration after 30 days on `warehouse/metadata/`,
#     under a comment claiming it "keeps snapshots for 30 days".
#
# Neither prefix matched anything. Iceberg lays tables out as
# `<warehouse>/<namespace>/<table>/{metadata,data}/...` and the configured
# namespace is `agentflow` (config/iceberg.yaml), so both rules were no-ops
# wearing the language of a retention policy -- which is the trap. The next
# person to notice they delete nothing reaches for the prefix the Flink sink
# actually writes (`warehouse/`, modules/flink/main.tf), and the no-op becomes
# a job that removes manifest lists and data files current snapshots reference.
#
# Snapshot expiry and orphan-file removal belong to the catalog, which knows
# what is still referenced: `iceberg_snapshot_expiry` in
# `src/agentflow_runtime/orchestration/dags/daily_batch.py`, and
# `docs/runbook.md` (`system.expire_snapshots`). What is left below is what S3
# alone owns: scratch state under `checkpoints/`, and the noncurrent versions
# this bucket accrues because versioning is enabled.
resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  # Checkpoints: Flink rewrites them constantly and never reads an old one.
  rule {
    id     = "checkpoint-cleanup"
    status = "Enabled"

    filter {
      prefix = "checkpoints/"
    }

    expiration {
      days = 7
    }
  }

  # Versioning is enabled on this bucket, so every overwrite and delete
  # leaves a noncurrent version behind forever. Expiring those touches no
  # object any snapshot can reference: a current object stays current.
  rule {
    id     = "noncurrent-version-cleanup"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expire_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket = aws_s3_bucket.lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "lake_bucket_name" {
  value = aws_s3_bucket.lake.id
}

output "lake_bucket_arn" {
  value = aws_s3_bucket.lake.arn
}

output "lake_kms_key_arn" {
  value = aws_kms_key.lake.arn
}
