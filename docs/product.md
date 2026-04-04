# Product Framework

## Problem Statement

AI agents serving end-users (customer support, ops automation, merchandising) need real-time, reliable data. Traditional data platforms serve dashboards with acceptable staleness (minutes to hours). Agents operating in conversation need sub-second freshness and explicit quality signals — stale or wrong data means hallucinated answers.

## Ideal Customer Profile (ICP)

- **Company**: Mid-to-large e-commerce or SaaS with AI-powered customer support
- **Team**: Data/platform engineering team (3-10 people) already running Kafka
- **Trigger**: Shipping AI agents that answer questions about orders, payments, inventory
- **Alternative**: Building bespoke API endpoints per agent use case (doesn't scale)

## Target Agent Use Cases

### 1. Customer Support Agent
- "What's the status of order ORD-20260404-1001?"
- "Why was the payment declined?"
- "What products are currently out of stock?"
- **Needs**: entity lookups (order, user, product), sub-second freshness

### 2. Operations Agent
- "What's our conversion rate in the last hour?"
- "Are there any pipeline issues I should know about?"
- "Show me orders with unusually high amounts today"
- **Needs**: real-time metrics, health status, anomaly signals

### 3. Merchandising Agent
- "What are the top selling products this week?"
- "Which categories have declining conversion?"
- **Needs**: aggregated metrics, trend queries, product catalog

## Success Metrics

| Metric | Target | How measured |
|--------|--------|-------------|
| Data freshness p99 | < 30 seconds | Prometheus histogram |
| Agent API latency p50 | < 50ms | FastAPI metrics |
| Quality gate pass rate | > 99% | dead letter ratio |
| Agent query success rate | > 95% | 2xx / total requests |
| Cost per GB processed | < $0.001 | AWS Cost Explorer |

## MVP Scope

**In scope (v0.1):**
- Streaming ingestion (Kafka) for orders, payments, clicks, products
- Real-time processing (Flink) with validation + enrichment
- Entity lookups: order, user, product, session
- Metrics: revenue, order count, AOV, conversion rate, error rate
- Health endpoint with live/placeholder transparency
- API key auth + rate limiting
- Local demo mode with seeded data

**Out of scope (future):**
- Multi-tenant isolation (separate namespaces per agent team)
- Fine-grained RBAC (which agent can query which entities)
- Agent SDK / client library (currently raw HTTP)
- Custom metric definitions via API
- Real-time anomaly detection alerts pushed to agents
- Data governance / PII masking layer

## Constraints

- Must run locally without cloud credentials (docker-compose + DuckDB)
- Must not require Flink for API-only demo mode
- Must clearly separate demo vs production capabilities
- Health endpoint must never return false-positive "healthy" for unmonitored components
