variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "kafka_bootstrap" { type = string }
variable "kafka_cluster_arn" { type = string }
variable "s3_bucket_arn" { type = string }
variable "lake_kms_key_arn" { type = string }
variable "parallelism" { type = number }
variable "parallelism_per_kpu" { type = number }
variable "permissions_boundary_arn" { type = string }

locals {
  # arn:…:cluster/NAME/UUID → arn:…:topic/NAME/UUID and arn:…:group/NAME/UUID,
  # the resource shapes MSK IAM auth authorizes topics and consumer groups on.
  kafka_topic_arn_prefix = replace(var.kafka_cluster_arn, ":cluster/", ":topic/")
  kafka_group_arn_prefix = replace(var.kafka_cluster_arn, ":cluster/", ":group/")
}

data "aws_subnet" "kafka" {
  for_each = toset(var.subnet_ids)
  id       = each.value
}

resource "aws_security_group" "flink" {
  name_prefix = "agentflow-flink-${var.environment}-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 9092
    to_port     = 9098
    protocol    = "tcp"
    cidr_blocks = [for s in data.aws_subnet.kafka : s.cidr_block]
    description = "Kafka brokers in cluster subnets"
  }

  # S3 (lake, checkpoints, application jar) and AWS APIs are public TLS
  # endpoints — this one cannot be CIDR-scoped without VPC endpoints, which are
  # operator-owned here.
  #trivy:ignore:AVD-AWS-0104
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "AWS APIs and S3 over TLS"
  }
}

resource "aws_iam_role" "flink" {
  name                 = "agentflow-flink-${var.environment}"
  permissions_boundary = var.permissions_boundary_arn

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
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
        ]
        Resource = [var.lake_kms_key_arn]
      },
    ]
  })
}

# MSK IAM auth data-plane permissions for the application's service role.
resource "aws_iam_role_policy" "flink_msk" {
  name = "flink-msk-iam-auth"
  role = aws_iam_role.flink.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:Connect",
          "kafka-cluster:DescribeCluster",
        ]
        Resource = [var.kafka_cluster_arn]
      },
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:DescribeTopic",
          "kafka-cluster:ReadData",
          "kafka-cluster:WriteData",
        ]
        Resource = ["${local.kafka_topic_arn_prefix}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "kafka-cluster:DescribeGroup",
          "kafka-cluster:AlterGroup",
        ]
        Resource = ["${local.kafka_group_arn_prefix}/*"]
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
        configuration_type            = "CUSTOM"
        checkpointing_enabled         = true
        checkpoint_interval           = 30000
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
          # MSK IAM auth (bootstrap points at the SASL/IAM listener, port 9098).
          "security.protocol"                  = "SASL_SSL"
          "sasl.mechanism"                     = "AWS_MSK_IAM"
          "sasl.jaas.config"                   = "software.amazon.msk.auth.iam.IAMLoginModule required;"
          "sasl.client.callback.handler.class" = "software.amazon.msk.auth.iam.IAMClientCallbackHandler"
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
