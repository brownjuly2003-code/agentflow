variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "agentflow"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC ID for network resources"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for Kafka, Flink, etc."
  type        = list(string)
}

# ── Kafka ───────────────────────────────────────────────────────

variable "kafka_instance_type" {
  description = "MSK broker instance type"
  type        = string
  default     = "kafka.m5.large"
}

variable "kafka_broker_count" {
  description = "Number of Kafka brokers"
  type        = number
  default     = 3
}

variable "kafka_ebs_volume_size_gb" {
  description = "EBS volume size per broker in GB"
  type        = number
  default     = 100
}

# ── Flink ───────────────────────────────────────────────────────

variable "flink_parallelism" {
  description = "Flink application parallelism"
  type        = number
  default     = 4
}

variable "flink_parallelism_per_kpu" {
  description = "Parallelism per KPU for auto-scaling"
  type        = number
  default     = 1
}

# ── Storage ─────────────────────────────────────────────────────

variable "storage_glacier_after_days" {
  description = "Days before transitioning to Glacier"
  type        = number
  default     = 90
}

variable "storage_expire_after_days" {
  description = "Days before expiring objects"
  type        = number
  default     = 365
}

# ── Monitoring ──────────────────────────────────────────────────

variable "sns_alert_topic_arn" {
  description = "SNS topic ARN for pipeline alerts"
  type        = string
  default     = ""
}

variable "freshness_sla_seconds" {
  description = "Maximum acceptable end-to-end latency in seconds"
  type        = number
  default     = 30
}
