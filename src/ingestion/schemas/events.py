"""Canonical event schemas for all data sources.

These Pydantic models serve as the single source of truth for event structure.
Used by producers (serialization), Flink jobs (validation), and the API (response types).
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class EventType(StrEnum):
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    PAYMENT_INITIATED = "payment.initiated"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    CLICK = "click"
    PAGE_VIEW = "page_view"
    ADD_TO_CART = "add_to_cart"
    PRODUCT_UPDATED = "product.updated"


class Currency(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class BaseEvent(BaseModel):
    event_id: str = Field(..., pattern=r"^[a-f0-9\-]{36}$")
    event_type: EventType
    timestamp: datetime
    source: str = Field(..., min_length=1, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def timestamp_not_future(cls, v: datetime) -> datetime:
        now = datetime.now(UTC)
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        # Allow 5 minutes of clock skew
        max_future = now.timestamp() + 300
        if v.timestamp() > max_future:
            msg = f"Event timestamp {v} is too far in the future"
            raise ValueError(msg)
        return v


class OrderItem(BaseModel):
    product_id: str
    quantity: int = Field(..., gt=0, le=1000)
    unit_price: Decimal = Field(..., gt=0, decimal_places=2)


class OrderEvent(BaseEvent):
    order_id: str = Field(..., pattern=r"^ORD-\d{8}-\d{4,}$")
    user_id: str
    status: OrderStatus
    items: list[OrderItem] = Field(..., min_length=1)
    total_amount: Decimal = Field(..., gt=0)
    currency: Currency = Currency.USD

    @field_validator("total_amount")
    @classmethod
    def total_matches_items(cls, v: Decimal, info) -> Decimal:
        items = info.data.get("items")
        if items:
            expected = sum(item.quantity * item.unit_price for item in items)
            if abs(v - expected) > Decimal("0.01"):
                msg = f"Total {v} doesn't match sum of items {expected}"
                raise ValueError(msg)
        return v


class PaymentMethod(StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"


class PaymentEvent(BaseEvent):
    payment_id: str
    order_id: str = Field(..., pattern=r"^ORD-\d{8}-\d{4,}$")
    user_id: str
    amount: Decimal = Field(..., gt=0)
    currency: Currency = Currency.USD
    method: PaymentMethod
    status: str = Field(..., pattern=r"^(initiated|completed|failed|refunded)$")
    failure_reason: str | None = None


class ClickstreamEvent(BaseEvent):
    session_id: str
    user_id: str | None = None  # anonymous users allowed
    page_url: str
    referrer: str | None = None
    user_agent: str
    viewport_width: int | None = None
    product_id: str | None = None  # set if on a product page


class ProductEvent(BaseEvent):
    product_id: str
    name: str = Field(..., min_length=1, max_length=500)
    category: str
    price: Decimal = Field(..., ge=0)
    currency: Currency = Currency.USD
    in_stock: bool
    stock_quantity: int = Field(..., ge=0)
