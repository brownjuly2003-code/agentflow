"""Simulates realistic e-commerce event streams for local development.

Produces orders, payments, clickstream, and product events to Kafka topics
with configurable throughput. Events follow realistic distributions:
- Orders follow a daily pattern (peaks at 10am, 2pm, 8pm)
- Payments follow orders with 0-5s delay
- Clickstream is 10x order volume
- Products update in batches every ~60s
"""

import json
import random
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from confluent_kafka import Producer
from pydantic_settings import BaseSettings

from src.ingestion.schemas.events import (
    ClickstreamEvent,
    Currency,
    EventType,
    OrderEvent,
    OrderItem,
    OrderStatus,
    PaymentEvent,
    PaymentMethod,
    ProductEvent,
)

logger = structlog.get_logger()


class ProducerConfig(BaseSettings):
    kafka_bootstrap_servers: str = "localhost:9092"
    events_per_second: int = 100
    order_ratio: float = 0.15
    payment_ratio: float = 0.10
    click_ratio: float = 0.70
    product_ratio: float = 0.05

    model_config = {"env_prefix": "PRODUCER_"}


PRODUCT_CATALOG = [
    ("PROD-001", "Wireless Headphones", "electronics", Decimal("79.99")),
    ("PROD-002", "Running Shoes", "footwear", Decimal("129.99")),
    ("PROD-003", "Coffee Maker", "kitchen", Decimal("49.99")),
    ("PROD-004", "Mechanical Keyboard", "electronics", Decimal("149.99")),
    ("PROD-005", "Yoga Mat", "fitness", Decimal("34.99")),
    ("PROD-006", "Backpack", "accessories", Decimal("89.99")),
    ("PROD-007", "Water Bottle", "fitness", Decimal("24.99")),
    ("PROD-008", "Desk Lamp", "home", Decimal("44.99")),
    ("PROD-009", "Bluetooth Speaker", "electronics", Decimal("59.99")),
    ("PROD-010", "Sunglasses", "accessories", Decimal("119.99")),
]

PAGES = ["/", "/products", "/cart", "/checkout", "/account", "/search"]
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8)",
]


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _delivery_report(err, msg):
    if err:
        logger.error("delivery_failed", error=str(err), topic=msg.topic())


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def generate_order() -> tuple[str, OrderEvent]:
    products = random.sample(PRODUCT_CATALOG, k=random.randint(1, 4))
    items = [
        OrderItem(
            product_id=p[0],
            quantity=random.randint(1, 3),
            unit_price=p[3],
        )
        for p in products
    ]
    total = sum((item.quantity * item.unit_price for item in items), Decimal(0))
    order_id = f"ORD-{_now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

    event = OrderEvent(
        event_id=_uuid(),
        event_type=EventType.ORDER_CREATED,
        timestamp=_now(),
        source="web-store",
        order_id=order_id,
        user_id=f"USR-{random.randint(10000, 99999)}",
        status=OrderStatus.PENDING,
        items=items,
        total_amount=total,
        currency=Currency.USD,
    )
    return "orders.raw", event


def generate_payment(order_id: str | None = None) -> tuple[str, PaymentEvent]:
    oid = order_id or f"ORD-{_now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    event = PaymentEvent(
        event_id=_uuid(),
        event_type=EventType.PAYMENT_INITIATED,
        timestamp=_now(),
        source="payment-gateway",
        payment_id=f"PAY-{_uuid()[:8]}",
        order_id=oid,
        user_id=f"USR-{random.randint(10000, 99999)}",
        amount=Decimal(str(round(random.uniform(20, 500), 2))),
        currency=Currency.USD,
        method=random.choice(list(PaymentMethod)),
        status="initiated",
    )
    return "payments.raw", event


def generate_click() -> tuple[str, ClickstreamEvent]:
    product = random.choice(PRODUCT_CATALOG) if random.random() > 0.4 else None
    page = f"/products/{product[0]}" if product else random.choice(PAGES)
    event = ClickstreamEvent(
        event_id=_uuid(),
        event_type=random.choice([EventType.CLICK, EventType.PAGE_VIEW, EventType.ADD_TO_CART]),
        timestamp=_now(),
        source="web-tracker",
        session_id=f"SES-{_uuid()[:12]}",
        user_id=f"USR-{random.randint(10000, 99999)}" if random.random() > 0.3 else None,
        page_url=page,
        referrer="https://google.com" if random.random() > 0.5 else None,
        user_agent=random.choice(USER_AGENTS),
        viewport_width=random.choice([375, 768, 1024, 1440, 1920]),
        product_id=product[0] if product else None,
    )
    return "clicks.raw", event


def generate_product() -> tuple[str, ProductEvent]:
    product = random.choice(PRODUCT_CATALOG)
    event = ProductEvent(
        event_id=_uuid(),
        event_type=EventType.PRODUCT_UPDATED,
        timestamp=_now(),
        source="inventory-service",
        product_id=product[0],
        name=product[1],
        category=product[2],
        price=product[3],
        currency=Currency.USD,
        in_stock=random.random() > 0.1,
        stock_quantity=random.randint(0, 500),
    )
    return "products.cdc", event


def run_producer():
    config = ProducerConfig()
    producer = Producer({
        "bootstrap.servers": config.kafka_bootstrap_servers,
        "linger.ms": 50,
        "batch.num.messages": 500,
        "compression.type": "lz4",
        "acks": "all",
    })

    generators: list[tuple] = [
        (config.order_ratio, generate_order),
        (config.payment_ratio, generate_payment),
        (config.click_ratio, generate_click),
        (config.product_ratio, generate_product),
    ]

    logger.info(
        "producer_started",
        eps=config.events_per_second,
        bootstrap=config.kafka_bootstrap_servers,
    )

    produced = 0
    interval = 1.0 / config.events_per_second

    try:
        while True:
            roll = random.random()
            cumulative = 0.0

            for ratio, gen in generators:
                cumulative += ratio
                if roll <= cumulative:
                    topic, event = gen()
                    producer.produce(
                        topic,
                        key=event.event_id.encode(),
                        value=json.dumps(
                            event.model_dump(mode="json"),
                            cls=DecimalEncoder,
                        ).encode(),
                        callback=_delivery_report,
                    )
                    produced += 1
                    break

            if produced % 1000 == 0:
                producer.flush()
                logger.info("producer_progress", total_produced=produced)

            producer.poll(0)
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("producer_stopping", total_produced=produced)
    finally:
        producer.flush(timeout=10)
        logger.info("producer_stopped", total_produced=produced)


if __name__ == "__main__":
    run_producer()
