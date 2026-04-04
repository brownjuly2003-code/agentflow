output "kafka_bootstrap_brokers" {
  description = "Kafka bootstrap broker connection string"
  value       = module.kafka.bootstrap_brokers
}

output "flink_application_arn" {
  description = "ARN of the Managed Flink application"
  value       = module.flink.application_arn
}

output "lake_bucket_name" {
  description = "S3 bucket name for the data lake"
  value       = module.storage.lake_bucket_name
}

output "lake_bucket_arn" {
  description = "S3 bucket ARN for the data lake"
  value       = module.storage.lake_bucket_arn
}

output "grafana_workspace_url" {
  description = "Grafana workspace URL"
  value       = module.monitoring.grafana_workspace_url
}
