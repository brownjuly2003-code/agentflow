"""Load test for the Agent Query API.

Simulates realistic AI agent traffic patterns:
- 40% entity lookups (order, user, product)
- 30% metric queries
- 20% natural language queries
- 10% health checks

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host http://localhost:8000

    # Headless (CI):
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
        --headless -u 50 -r 10 --run-time 60s
"""

import os
import random

from locust import HttpUser, between, task

ORDERS = [f"ORD-20260404-{i}" for i in range(1001, 1009)]
USERS = [f"USR-{i}" for i in range(10001, 10006)]
PRODUCTS = [f"PROD-{i:03d}" for i in range(1, 11)]
METRICS = ["revenue", "order_count", "avg_order_value", "conversion_rate", "error_rate"]
WINDOWS = ["5m", "15m", "1h", "6h", "24h"]

NL_QUESTIONS = [
    "What is the revenue today?",
    "What is the average order value in the last hour?",
    "Show me top 5 products",
    "What is the conversion rate in the last 24 hours?",
    "How many active sessions right now?",
    "Which products are out of stock?",
]


class AgentUser(HttpUser):
    """Simulates an AI agent making queries to the data platform."""

    wait_time = between(0.1, 0.5)

    def on_start(self):
        api_key = os.getenv("AGENTFLOW_LOAD_API_KEY", "").strip()
        self.request_headers = {"X-API-Key": api_key} if api_key else None

    @task(4)
    def entity_lookup(self):
        """Look up a random entity."""
        roll = random.random()
        if roll < 0.4:
            oid = random.choice(ORDERS)
            self.client.get(
                f"/v1/entity/order/{oid}",
                headers=self.request_headers,
                name="/v1/entity/order/{id}",
            )
        elif roll < 0.7:
            uid = random.choice(USERS)
            self.client.get(
                f"/v1/entity/user/{uid}",
                headers=self.request_headers,
                name="/v1/entity/user/{id}",
            )
        else:
            pid = random.choice(PRODUCTS)
            self.client.get(
                f"/v1/entity/product/{pid}",
                headers=self.request_headers,
                name="/v1/entity/product/{id}",
            )

    @task(3)
    def metric_query(self):
        """Query a random metric."""
        metric = random.choice(METRICS)
        window = random.choice(WINDOWS)
        self.client.get(
            f"/v1/metrics/{metric}?window={window}",
            headers=self.request_headers,
            name="/v1/metrics/{name}",
        )

    @task(2)
    def nl_query(self):
        """Send a natural language query."""
        question = random.choice(NL_QUESTIONS)
        self.client.post(
            "/v1/query",
            headers=self.request_headers,
            json={"question": question},
            name="/v1/query",
        )

    @task(2)
    def batch_query(self):
        """Send a mixed batch request."""
        self.client.post(
            "/v1/batch",
            headers=self.request_headers,
            json={
                "requests": [
                    {
                        "id": "entity-1",
                        "type": "entity",
                        "params": {
                            "entity_type": "order",
                            "entity_id": random.choice(ORDERS),
                        },
                    },
                    {
                        "id": "metric-1",
                        "type": "metric",
                        "params": {
                            "name": random.choice(METRICS),
                            "window": random.choice(WINDOWS),
                        },
                    },
                    {
                        "id": "query-1",
                        "type": "query",
                        "params": {
                            "question": random.choice(NL_QUESTIONS),
                        },
                    },
                ]
            },
            name="/v1/batch",
        )

    @task(1)
    def health_check(self):
        """Check pipeline health."""
        self.client.get("/v1/health", headers=self.request_headers, name="/v1/health")
