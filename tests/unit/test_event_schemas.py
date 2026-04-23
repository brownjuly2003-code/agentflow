import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.ingestion.schemas.events import Currency, OrderEvent, PaymentEvent, ProductEvent


def test_order_valid_minimal(sample_order_event) -> None:
    payload = dict(sample_order_event)
    payload.pop("currency")

    event = OrderEvent.model_validate(payload)

    assert event.currency is Currency.USD
    assert event.total_amount == Decimal("209.97")
    assert event.items[0].product_id == "PROD-001"


def test_order_total_matches_items(sample_order_event) -> None:
    event = OrderEvent.model_validate(sample_order_event)

    expected = sum(item.quantity * item.unit_price for item in event.items)

    assert event.total_amount == expected


def test_order_total_mismatch_raises(sample_order_event) -> None:
    payload = {**sample_order_event, "total_amount": "1.00"}

    with pytest.raises(ValidationError) as exc_info:
        OrderEvent.model_validate(payload)

    assert any(
        error["loc"] == ("total_amount",) and "doesn't match sum of items" in error["msg"]
        for error in exc_info.value.errors(include_url=False)
    )


def test_order_rejects_negative_amount(sample_order_event) -> None:
    payload = {**sample_order_event, "total_amount": "-1.00"}

    with pytest.raises(ValidationError) as exc_info:
        OrderEvent.model_validate(payload)

    assert any(
        error["loc"] == ("total_amount",) for error in exc_info.value.errors(include_url=False)
    )


def test_order_currency_defaults_to_usd(sample_order_event) -> None:
    payload = dict(sample_order_event)
    payload.pop("currency")

    event = OrderEvent.model_validate(payload)

    assert event.currency is Currency.USD


def test_order_rejects_unknown_currency(sample_order_event) -> None:
    payload = {**sample_order_event, "currency": "JPY"}

    with pytest.raises(ValidationError) as exc_info:
        OrderEvent.model_validate(payload)

    assert any(error["loc"] == ("currency",) for error in exc_info.value.errors(include_url=False))


def test_order_item_rejects_zero_quantity(sample_order_event) -> None:
    payload = {
        **sample_order_event,
        "items": [
            {"product_id": "PROD-001", "quantity": 0, "unit_price": "79.99"},
        ],
        "total_amount": "0.00",
    }

    with pytest.raises(ValidationError) as exc_info:
        OrderEvent.model_validate(payload)

    assert any(
        error["loc"] == ("items", 0, "quantity")
        for error in exc_info.value.errors(include_url=False)
    )


def test_payment_timestamp_assumes_utc_for_naive_datetime(sample_payment_event) -> None:
    naive_timestamp = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    payload = {
        **sample_payment_event,
        "timestamp": naive_timestamp,
    }

    event = PaymentEvent.model_validate(payload)

    assert event.timestamp == naive_timestamp.replace(tzinfo=UTC)


def test_payment_rejects_future_timestamp(sample_payment_event) -> None:
    payload = {
        **sample_payment_event,
        "timestamp": datetime.now(UTC) + timedelta(minutes=10),
    }

    with pytest.raises(ValidationError) as exc_info:
        PaymentEvent.model_validate(payload)

    assert any(
        error["loc"] == ("timestamp",) and "too far in the future" in error["msg"]
        for error in exc_info.value.errors(include_url=False)
    )


def test_product_price_positive_or_zero() -> None:
    event = ProductEvent.model_validate(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "product.updated",
            "timestamp": datetime.now(UTC),
            "source": "inventory-service",
            "product_id": "PROD-001",
            "name": "Wireless Headphones",
            "category": "electronics",
            "price": "0.00",
            "currency": "USD",
            "in_stock": False,
            "stock_quantity": 0,
        }
    )

    assert event.price == Decimal("0.00")


def test_product_rejects_negative_price() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProductEvent.model_validate(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "product.updated",
                "timestamp": datetime.now(UTC),
                "source": "inventory-service",
                "product_id": "PROD-001",
                "name": "Wireless Headphones",
                "category": "electronics",
                "price": "-0.01",
                "currency": "USD",
                "in_stock": True,
                "stock_quantity": 10,
            }
        )

    assert any(error["loc"] == ("price",) for error in exc_info.value.errors(include_url=False))
