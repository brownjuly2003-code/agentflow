terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  backend "s3" {
    bucket         = "agentflow-terraform-state"
    key            = "infrastructure/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "agentflow-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "agentflow"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Modules ─────────────────────────────────────────────────────

module "kafka" {
  source = "./modules/kafka"

  environment        = var.environment
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
  instance_type      = var.kafka_instance_type
  broker_count       = var.kafka_broker_count
  ebs_volume_size_gb = var.kafka_ebs_volume_size_gb
}

module "flink" {
  source = "./modules/flink"

  environment         = var.environment
  vpc_id              = var.vpc_id
  subnet_ids          = var.private_subnet_ids
  kafka_bootstrap     = module.kafka.bootstrap_brokers
  s3_bucket_arn       = module.storage.lake_bucket_arn
  parallelism         = var.flink_parallelism
  parallelism_per_kpu = var.flink_parallelism_per_kpu
}

module "storage" {
  source = "./modules/storage"

  environment            = var.environment
  lake_bucket_name       = "${var.project_name}-lake-${var.environment}"
  lifecycle_glacier_days = var.storage_glacier_after_days
  lifecycle_expire_days  = var.storage_expire_after_days
}

module "monitoring" {
  source = "./modules/monitoring"

  environment           = var.environment
  kafka_cluster_arn     = module.kafka.cluster_arn
  flink_application_arn = module.flink.application_arn
  sns_alert_topic_arn   = var.sns_alert_topic_arn
  freshness_sla_seconds = var.freshness_sla_seconds
}
