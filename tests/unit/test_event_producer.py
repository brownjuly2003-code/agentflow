"""Unit tests for the synthetic event producer.

Closes the coverage gap on `src/ingestion/producers/event_producer.py`
flagged in Codex audit p5. We exercise the four generators, the Decimal
JSON encoder, and the producer loop control path without a live Kafka
broker (Producer is mocked via patch).
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.producers import event_producer as producer_module
from src.ingestion.producers.event_producer import (
    DecimalEncoder,
    generate_click,
    generate_order,
    generate_payment,
    generate_product,
)
from src.ingestion.schemas.events import (
    ClickstreamEvent,
    OrderEvent,
    PaymentEvent,
    ProductEvent,
)


def test_generate_order_returns_topic_and_validating_model():
    topic, event = generate_order()
    assert topic == "orders.raw"
    assert isinstance(event, OrderEvent)
    # Items multiply out to total_amount via the model — sanity check the math
    expected_total = sum((item.quantity * item.unit_price for item in event.items), Decimal(0))
    assert event.total_amount == expected_total
    assert event.order_id.startswith("ORD-")
    assert event.user_id.startswith("USR-")


def test_generate_payment_can_attach_to_existing_order():
    # OrderEvent regex requires ORD-YYYYMMDD-NNNN pattern
    topic, event = generate_payment(order_id="ORD-20260427-0001")
    assert topic == "payments.raw"
    assert isinstance(event, PaymentEvent)
    assert event.order_id == "ORD-20260427-0001"


def test_generate_payment_falls_back_to_random_order():
    topic, event = generate_payment()
    assert topic == "payments.raw"
    assert event.order_id.startswith("ORD-")


def test_generate_click_returns_validating_clickstream_event():
    topic, event = generate_click()
    assert topic == "clicks.raw"
    assert isinstance(event, ClickstreamEvent)
    assert event.session_id.startswith("SES-")


def test_generate_product_picks_an_entry_from_catalog():
    topic, event = generate_product()
    assert topic == "products.cdc"
    assert isinstance(event, ProductEvent)
    assert event.product_id.startswith("PROD-")
    assert isinstance(event.price, Decimal)


def test_decimal_encoder_serializes_decimal_to_float():
    payload = {"amount": Decimal("19.99"), "qty": 3}
    encoded = json.dumps(payload, cls=DecimalEncoder)
    assert '"amount": 19.99' in encoded


def test_decimal_encoder_falls_through_for_unsupported_types():
    class Custom:
        pass

    with pytest.raises(TypeError):
        json.dumps({"x": Custom()}, cls=DecimalEncoder)


def test_run_producer_flushes_on_keyboard_interrupt():
    fake_producer = MagicMock()
    # produce() must succeed; sleep simulates the loop's interval; we raise
    # KeyboardInterrupt on the second pass to exit the generator loop.
    sleeps = [None, KeyboardInterrupt()]

    def _sleep(_):
        next_value = sleeps.pop(0)
        if isinstance(next_value, BaseException):
            raise next_value

    with patch.object(producer_module, "Producer", return_value=fake_producer), patch.object(
        producer_module.time, "sleep", side_effect=_sleep
    ), patch.dict(
        "os.environ", {"PRODUCER_EVENTS_PER_SECOND": "10"}, clear=False
    ):
        producer_module.run_producer()

    # Producer is created once and flushed on the way out.
    fake_producer.flush.assert_called_once()
    # produce() was called at least once before the loop exited.
    assert fake_producer.produce.call_count >= 1


def test_delivery_report_logs_on_error():
    err = MagicMock(__str__=lambda self: "delivery-failed")
    msg = MagicMock()
    msg.topic.return_value = "orders.raw"
    with patch.object(producer_module, "logger") as logger:
        producer_module._delivery_report(err, msg)
    logger.error.assert_called_once()
