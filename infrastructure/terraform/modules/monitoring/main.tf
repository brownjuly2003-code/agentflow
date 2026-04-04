variable "environment" { type = string }
variable "kafka_cluster_arn" { type = string }
variable "flink_application_arn" { type = string }
variable "sns_alert_topic_arn" { type = string }
variable "freshness_sla_seconds" { type = number }

# ── CloudWatch Alarms ───────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "kafka_under_replicated" {
  alarm_name          = "agentflow-${var.environment}-kafka-under-replicated"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnderReplicatedPartitions"
  namespace           = "AWS/Kafka"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Kafka has under-replicated partitions"
  alarm_actions       = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []

  dimensions = {
    "Cluster Name" = split("/", var.kafka_cluster_arn)[1]
  }
}

resource "aws_cloudwatch_metric_alarm" "kafka_disk_usage" {
  alarm_name          = "agentflow-${var.environment}-kafka-disk-80pct"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "KafkaDataLogsDiskUsed"
  namespace           = "AWS/Kafka"
  period              = 300
  statistic           = "Maximum"
  threshold           = 80
  alarm_description   = "Kafka broker disk usage above 80%"
  alarm_actions       = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []

  dimensions = {
    "Cluster Name" = split("/", var.kafka_cluster_arn)[1]
  }
}

resource "aws_cloudwatch_metric_alarm" "flink_checkpoint_failure" {
  alarm_name          = "agentflow-${var.environment}-flink-checkpoint-fail"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "numberOfFailedCheckpoints"
  namespace           = "AWS/KinesisAnalytics"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Flink checkpoint failures detected"
  alarm_actions       = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []

  dimensions = {
    Application = split("/", var.flink_application_arn)[1]
  }
}

resource "aws_cloudwatch_metric_alarm" "flink_downtime" {
  alarm_name          = "agentflow-${var.environment}-flink-downtime"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "downtime"
  namespace           = "AWS/KinesisAnalytics"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Flink application is down"
  alarm_actions       = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []

  dimensions = {
    Application = split("/", var.flink_application_arn)[1]
  }
}

# ── Grafana Workspace ───────────────────────────────────────────

resource "aws_grafana_workspace" "main" {
  name                     = "agentflow-${var.environment}"
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "SERVICE_MANAGED"
  role_arn                 = aws_iam_role.grafana.arn

  data_sources = ["CLOUDWATCH", "PROMETHEUS"]
}

resource "aws_iam_role" "grafana" {
  name = "agentflow-grafana-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "grafana.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "grafana_cloudwatch" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

output "grafana_workspace_url" {
  value = aws_grafana_workspace.main.endpoint
}
