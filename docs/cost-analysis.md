# Cost Analysis

## Scenario
- 10 TB/day ingestion volume
- ~115k events/sec average (peaks at 200k)
- 30-day hot retention, 90-day warm, 365-day cold
- us-east-1 region

## Component Breakdown

### Kafka (Amazon MSK)

| Config | Baseline | Optimized |
|--------|----------|-----------|
| Instance type | kafka.m5.large (3 brokers) | kafka.m5.large (3 brokers) |
| Storage | 100GB EBS per broker | Tiered storage (S3 offload after 24h) |
| Monthly | $2,400 | $1,800 |

**Optimization**: Tiered storage offloads older segments to S3 at $0.023/GB vs $0.10/GB for EBS. Saves ~25% on storage costs for 7-day retention.

### Flink (Amazon Managed Flink)

| Config | Baseline | Optimized |
|--------|----------|-----------|
| KPUs | 8 (fixed) | 4-12 (autoscaling) |
| Parallelism | 8 | 4-12 |
| Monthly | $1,900 | $1,400 |

**Optimization**: Autoscaling reduces KPUs during off-peak hours (11pm-7am = 60% less traffic). Average utilization drops from 8 KPU to ~5.5 KPU.

### Storage (S3 + Iceberg)

| Tier | Volume | Storage class | Monthly |
|------|--------|--------------|---------|
| Hot (0-30d) | 300 TB | S3 Standard | $400 |
| Warm (30-90d) | 600 TB | S3 IA | $100 |
| Cold (90-365d) | 2.7 PB | Glacier | $20 |
| **Total** | | | **$520** |

**Optimization**: Lifecycle rules automate tiering. Iceberg snapshot expiry (30-day) prevents metadata bloat. Partition pruning reduces scan costs by ~80%.

### API (ECS Fargate)

| Config | Baseline | Optimized |
|--------|----------|-----------|
| Tasks | 4 × 0.5 vCPU, 1GB | 2-6 × 0.5 vCPU, 1GB (autoscaling) |
| Spot capacity | 0% | 70% |
| Monthly | $340 | $280 |

**Optimization**: Fargate Spot for non-critical capacity. API is stateless, so Spot interruptions are handled by ALB draining.

### Monitoring

| Component | Monthly |
|-----------|---------|
| CloudWatch (logs + metrics) | $120 |
| Managed Grafana | $9 |
| Prometheus (AMP) | $51 |
| **Total** | **$180** |

## Total Cost

| | Baseline | Optimized | Savings |
|--|----------|-----------|---------|
| Kafka | $2,400 | $1,800 | 25% |
| Flink | $1,900 | $1,400 | 26% |
| Storage | $680 | $520 | 24% |
| API | $340 | $280 | 18% |
| Monitoring | $180 | $180 | 0% |
| **Total** | **$5,500** | **$4,180** | **24%** |

## Cost per GB

| Metric | Value |
|--------|-------|
| Ingestion cost | $0.00014/GB |
| Processing cost | $0.00005/GB |
| Storage cost (hot) | $0.023/GB/month |
| Total cost per GB processed | $0.00019/GB |

## Scaling Projections

| Volume | Monthly cost | Cost/GB |
|--------|-------------|---------|
| 1 TB/day | $2,100 | $0.00069 |
| 10 TB/day | $4,180 | $0.00014 |
| 50 TB/day | $12,500 | $0.000082 |
| 100 TB/day | $21,000 | $0.000069 |

Economy of scale: 100 TB/day is only 5x the cost of 10 TB/day (not 10x) due to Kafka tiered storage and Flink autoscaling.
