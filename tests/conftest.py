"""Shared fixtures for unit and integration tests."""

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "sdk"))


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
