"""Shared fixtures for unit and integration tests."""

import os
import uuid
from datetime import UTC, datetime

import pytest

# ADR 0006: DuckDB is the local-dev / test store. Pin it explicitly so the test
# suite stays deterministic regardless of the shipped serving default (which is
# moving to ClickHouse per the cutover plan). `setdefault` lets an opt-in
# ClickHouse test lane still override it via SERVING_BACKEND.
os.environ.setdefault("SERVING_BACKEND", "duckdb")

# The suite asserts on the canonical demo entities (PROD-001, ORD-20260404-1001,
# the two seeded dead-letter rows), so it runs the seeded profile. The *shipped*
# default is off: seeding used to happen inside QueryEngine's constructor on
# every boot, before any flag was read, which put demo rows into whatever store
# the API was pointed at (audit P0-2). Tests that pin the shipped default
# monkeypatch this back off — see tests/unit/test_serving_provisioning.py.
os.environ.setdefault("AGENTFLOW_SEED_ON_BOOT", "true")


@pytest.fixture
def sample_order_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "order.created",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "web-store",
        "order_id": f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-1234",
        "user_id": "USR-10001",
        "status": "pending",
        "items": [
            {"product_id": "PROD-001", "quantity": 2, "unit_price": "79.99"},
            {"product_id": "PROD-003", "quantity": 1, "unit_price": "49.99"},
        ],
        "total_amount": "209.97",
        "currency": "USD",
    }


@pytest.fixture
def sample_payment_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "payment.initiated",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "payment-gateway",
        "payment_id": f"PAY-{uuid.uuid4().hex[:8]}",
        "order_id": f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-1234",
        "user_id": "USR-10001",
        "amount": "209.97",
        "currency": "USD",
        "method": "card",
        "status": "initiated",
    }


@pytest.fixture
def sample_click_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "page_view",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "web-tracker",
        "session_id": f"SES-{uuid.uuid4().hex[:12]}",
        "user_id": "USR-10001",
        "page_url": "/products/PROD-001",
        "referrer": "https://google.com",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "viewport_width": 1440,
        "product_id": "PROD-001",
    }


@pytest.fixture
def sample_invalid_event() -> dict:
    return {
        "event_id": "not-a-valid-uuid",
        "event_type": "unknown.type",
        "timestamp": "2020-01-01T00:00:00Z",
        "source": "test",
    }
