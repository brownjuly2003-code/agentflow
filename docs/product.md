# Product Framework

## Problem Statement

AgentFlow is a data serving layer for AI agents, not a BI dashboard stack. It exists for teams whose agents need fresh answers about orders, inventory, users, revenue, and pipeline state while a conversation is still happening. If the data is six hours old, the agent is wrong in real time.

## Who AgentFlow Is For

**Primary ICP**: Engineering teams of 5-50 people building AI agents that need to answer business-operations questions with sub-minute data freshness.

**Best-fit companies**:
- E-commerce and SaaS teams with support, ops, or merchandising agents
- Teams already producing event data and feeling the gap between dashboards and agent-grade serving
- Platform groups that do not want to hand-build one-off APIs per agent workflow

**Trigger**: "Our support agent is answering questions about order status with 6-hour-old data because we are still on batch ETL."

**Decision maker**: Head of Data Engineering or VP Engineering.

**Economic buyer**: Head of Data Engineering, VP Engineering, or CTO at an early-stage company.

**Champion**: Staff or Senior Data Engineer who owns the data platform and keeps getting asked for agent-specific APIs.

**Anti-ICP**:
- Teams that only need BI dashboards and scheduled reporting
- Teams with fewer than 1K events per day where batch ETL is still good enough
- Pure inference platforms that do not serve operational business data

## Three Core User Journeys

### 1. Support Agent Answers Order Status

**Time to first answer**: 15 minutes from `make demo`

**Before**: Support uses a bot backed by stale warehouse tables or fragile custom APIs. A simple "where is my order?" question turns into a fallback to a human queue.

**After**: The support agent reads live order state and customer context from one SDK and answers in the same conversation turn.

**Step-by-step**:
1. Run `make demo` to seed the local pipeline and start the API.
2. Install the SDK with `pip install agentflow-client` (or `python -m pip install -e "./sdk"` when working from this repo).
3. Pass the order ID from the support ticket into the agent workflow.
4. Read the order and the associated user profile from AgentFlow.

```python
from agentflow import AgentFlowClient

client = AgentFlowClient(
    "http://localhost:8000",
    api_key="af-prod-agent-support-abc123",
)

def answer_order_status(order_id: str) -> str:
    order = client.get_order(order_id)
    user = client.get_user(order.user_id)
    return (
        f"Order {order.order_id} is {order.status}. "
        f"Customer lifetime orders: {user.total_orders}. "
        f"Lifetime spend: ${user.total_spent:.2f}."
    )
```

### 2. Ops Agent Monitors Pipeline Health

**Time to alert**: 30 seconds

**Before**: Ops learns that data is stale only after agents start giving bad answers and an internal team complains.

**After**: An ops agent checks freshness and error rate continuously, then pages when the pipeline is unhealthy or freshness breaches the SLA.

**Step-by-step**:
1. Give the ops workflow an unrestricted API key.
2. Poll `health()` and `is_fresh(30)` every 30 seconds.
3. Attach `error_rate` so the alert includes probable severity.
4. Escalate immediately when freshness cannot be trusted.

```python
from agentflow import AgentFlowClient
from agentflow.exceptions import DataFreshnessError

ops = AgentFlowClient(
    "http://localhost:8000",
    api_key="af-prod-agent-ops-def456",
)

def check_pipeline() -> str:
    try:
        fresh = ops.is_fresh(30)
    except DataFreshnessError as exc:
        return f"PAGE: pipeline freshness check failed ({exc})"

    health = ops.health()
    error_rate = ops.get_metric("error_rate", "1h")
    return (
        f"status={health.status} "
        f"fresh={fresh} "
        f"error_rate_1h={error_rate.value:.4f}"
    )
```

### 3. Merch Agent Queries Revenue Metrics

**Time to insight**: under 1 minute

**Before**: Merchandising waits for a dashboard refresh or asks data engineering for a one-off SQL query.

**After**: A merch agent gets live KPIs plus catalog-backed results from the same semantic layer the support and ops agents use.

**Step-by-step**:
1. Reuse the same running AgentFlow API from `make demo`.
2. Install the SDK once for the agent environment.
3. Pull direct metrics for revenue and conversion.
4. Use natural-language query for ranked product output.

```python
from agentflow import AgentFlowClient

client = AgentFlowClient(
    "http://localhost:8000",
    api_key="af-prod-agent-ops-def456",
)

def merch_snapshot() -> dict:
    revenue = client.get_metric("revenue", "24h")
    conversion = client.get_metric("conversion_rate", "24h")
    top_products = client.query("Show me top 3 products")
    return {
        "revenue_24h_usd": revenue.value,
        "conversion_rate_24h": conversion.value,
        "top_products": top_products.answer,
    }
```

## Success Metrics

These are the product gates for market readiness, not assumptions that every local demo already satisfies.

| Metric | Target |
|--------|--------|
| Time to first agent response using live data | < 15 min from `make demo` |
| Data freshness | < 30 sec end-to-end |
| API p95 latency | < 100ms (entity), < 200ms (metric) |
| Data quality gate rejection rate | > 0% in any realistic demo |
| Developer onboarding time | < 5 min to first SDK call |

## MVP Scope vs Roadmap

| Area | In v1 now | Roadmap / production gap |
|------|-----------|--------------------------|
| Agent-facing API | Entity lookup, metrics, NL query, health, catalog, lineage, SSE stream | Richer query guardrails and async-first serving patterns |
| Agent integration | Python SDK v1 and exported OpenAPI tool definitions for Claude/OpenAI | SDK v2 with async streaming consumption, retries, and pagination helpers |
| Access control | Named API keys, per-key rate limits, and entity allow-lists | Full tenant isolation, RBAC, SSO, and audit export |
| Data plane | Local DuckDB-backed demo that proves the end-to-end path from ingestion to serving | Production Iceberg serving path, Trino/Athena federation, and autoscaled serving tier |
| Reliability | Health endpoint, benchmark report, and failure/integration tests | SLO dashboards, alert routing, and latency tuning to consistently hit target p95 |
| Governance | Schema and semantic quality gates before serving | PII masking, policy controls, retention, and compliance workflows |

## Constraints

- Must run locally without cloud credentials.
- Must not require Flink for the API-only demo path.
- Must distinguish local-demo behavior from production claims.
- Must never report freshness as trustworthy when the underlying signal is missing or unhealthy.
