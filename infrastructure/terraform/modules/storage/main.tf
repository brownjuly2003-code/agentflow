variable "environment" { type = string }
variable "lake_bucket_name" { type = string }
variable "lifecycle_glacier_days" { type = number }
variable "lifecycle_expire_days" { type = number }

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
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  # Raw data: move to Glacier after N days, expire after M days
  rule {
    id     = "raw-data-lifecycle"
    status = "Enabled"

    filter {
      prefix = "warehouse/raw/"
    }

    transition {
      days          = var.lifecycle_glacier_days
      storage_class = "GLACIER"
    }

    expiration {
      days = var.lifecycle_expire_days
    }
  }

  # Checkpoints: expire after 7 days
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

  # Iceberg metadata compaction: keep snapshots for 30 days
  rule {
    id     = "iceberg-metadata"
    status = "Enabled"

    filter {
      prefix = "warehouse/metadata/"
    }

    expiration {
      days = 30
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
