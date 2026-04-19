variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kafka_bootstrap" { type = string }
variable "s3_bucket_arn" { type = string }
variable "parallelism" { type = number }
variable "parallelism_per_kpu" { type = number }

resource "aws_security_group" "flink" {
  name_prefix = "agentflow-flink-${var.environment}-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }
}

resource "aws_iam_role" "flink" {
  name = "agentflow-flink-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "kinesisanalytics.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "flink_s3" {
  name = "flink-s3-access"
  role = aws_iam_role.flink.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
        ]
        Resource = [
          var.s3_bucket_arn,
          "${var.s3_bucket_arn}/*",
        ]
      },
    ]
  })
}

resource "aws_kinesisanalyticsv2_application" "stream_processor" {
  name                   = "agentflow-stream-processor-${var.environment}"
  runtime_environment    = "FLINK-1_19"
  service_execution_role = aws_iam_role.flink.arn

  application_configuration {
    application_code_configuration {
      code_content_type = "ZIPFILE"

      code_content {
        s3_content_location {
          bucket_arn = var.s3_bucket_arn
          file_key   = var.jar_s3_key
        }
      }
    }

    flink_application_configuration {
      checkpoint_configuration {
        configuration_type = "CUSTOM"
        checkpointing_enabled = true
        checkpoint_interval   = 30000
        min_pause_between_checkpoints = 10000
      }

      parallelism_configuration {
        configuration_type   = "CUSTOM"
        parallelism          = var.parallelism
        parallelism_per_kpu  = var.parallelism_per_kpu
        auto_scaling_enabled = var.environment == "prod"
      }
    }

    environment_properties {
      property_group {
        property_group_id = "kafka"
        property_map = {
          "bootstrap.servers" = var.kafka_bootstrap
          "group.id"          = "agentflow-stream-processor"
        }
      }

      property_group {
        property_group_id = "s3"
        property_map = {
          "bucket" = var.s3_bucket_arn
          "prefix" = "warehouse/"
        }
      }
    }
  }
}

output "application_arn" {
  value = aws_kinesisanalyticsv2_application.stream_processor.arn
}
