variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_type" { type = string }
variable "broker_count" { type = number }
variable "ebs_volume_size_gb" { type = number }

# Broker ingress is limited to the CIDRs of the subnets the cluster (and its
# clients — Flink runs in the same private subnets) actually lives in, not the
# whole 10.0.0.0/8. Broker-to-broker traffic stays allowed because the brokers'
# own subnets are in this same list.
data "aws_subnet" "client" {
  for_each = toset(var.subnet_ids)
  id       = each.value
}

resource "aws_security_group" "kafka" {
  name_prefix = "agentflow-kafka-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 9092
    to_port     = 9098
    protocol    = "tcp"
    cidr_blocks = [for s in data.aws_subnet.client : s.cidr_block]
    description = "Kafka broker ports (cluster + client subnets only)"
  }

  # Brokers only talk to each other (replication, KRaft) inside these subnets;
  # MSK control-plane and log/metric delivery go over service-managed ENIs, not
  # this security group.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [for s in data.aws_subnet.client : s.cidr_block]
    description = "Inter-broker traffic within cluster subnets"
  }
}

# Customer-managed key for broker EBS at-rest encryption (instead of the
# implicit aws/kafka key): rotation, usage audit and revocation stay in
# project control.
resource "aws_kms_key" "kafka" {
  description         = "agentflow ${var.environment} MSK at-rest encryption"
  enable_key_rotation = true
}

resource "aws_kms_alias" "kafka" {
  name          = "alias/agentflow-${var.environment}-kafka"
  target_key_id = aws_kms_key.kafka.key_id
}

resource "aws_msk_configuration" "main" {
  name              = "agentflow-${var.environment}"
  kafka_versions    = ["3.7.x.kraft"]
  server_properties = <<-EOT
    auto.create.topics.enable=false
    default.replication.factor=3
    min.insync.replicas=2
    num.partitions=6
    log.retention.hours=168
    log.retention.bytes=107374182400
    compression.type=lz4
    message.max.bytes=10485760
  EOT
}

resource "aws_msk_cluster" "main" {
  cluster_name           = "agentflow-${var.environment}"
  kafka_version          = "3.7.x.kraft"
  number_of_broker_nodes = var.broker_count

  broker_node_group_info {
    instance_type   = var.instance_type
    client_subnets  = var.subnet_ids
    security_groups = [aws_security_group.kafka.id]

    storage_info {
      ebs_storage_info {
        volume_size = var.ebs_volume_size_gb

        provisioned_throughput {
          enabled           = var.environment == "prod"
          volume_throughput = var.environment == "prod" ? 250 : null
        }
      }
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }

  # TLS-only client traffic + IAM client authentication: an in-VPC foothold
  # alone is no longer enough to read or write the event stream — a client
  # must present SigV4 credentials authorized for kafka-cluster:* actions.
  client_authentication {
    sasl {
      iam = true
    }
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.kafka.arn

    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  open_monitoring {
    prometheus {
      jmx_exporter {
        enabled_in_broker = true
      }
      node_exporter {
        enabled_in_broker = true
      }
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = "/aws/msk/agentflow-${var.environment}"
      }
    }
  }
}

# SASL/IAM endpoints (port 9098). The plaintext bootstrap_brokers attribute is
# empty once client_broker = "TLS", so it is deliberately not exported.
output "bootstrap_brokers_sasl_iam" {
  value = aws_msk_cluster.main.bootstrap_brokers_sasl_iam
}

output "cluster_arn" {
  value = aws_msk_cluster.main.arn
}
