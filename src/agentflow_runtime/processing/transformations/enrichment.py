"""Event enrichment functions for the processing layer.

Pure functions that add derived fields to events. Used by Flink jobs
and batch transformations alike — keeping logic DRY across streaming and batch.
"""

from decimal import Decimal

ORDER_SIZE_SMALL_MAX_TOTAL = Decimal("50")
ORDER_SIZE_MEDIUM_MAX_TOTAL = Decimal("200")
ORDER_SIZE_LARGE_MAX_TOTAL = Decimal("1000")
MOBILE_VIEWPORT_MAX_WIDTH = 768
PAYMENT_RISK_HIGH_AMOUNT_THRESHOLD = 500
PAYMENT_RISK_MEDIUM_AMOUNT_THRESHOLD = 200
PAYMENT_RISK_HIGH_SCORE_THRESHOLD = 0.5
PAYMENT_RISK_MEDIUM_SCORE_THRESHOLD = 0.2


def enrich_order(event: dict) -> dict:
    """Add derived fields to an order event.

    Adds:
    - item_count: total number of items
    - unique_products: number of distinct products
    - avg_item_price: average price per item
    - order_size_bucket: small/medium/large/whale
    """
    items = event.get("items", [])
    total = Decimal(str(event.get("total_amount", 0)))

    item_count = sum(i.get("quantity", 0) for i in items)
    unique_products = len({i["product_id"] for i in items if "product_id" in i})
    avg_price = total / item_count if item_count > 0 else Decimal("0")

    if total < ORDER_SIZE_SMALL_MAX_TOTAL:
        bucket = "small"
    elif total < ORDER_SIZE_MEDIUM_MAX_TOTAL:
        bucket = "medium"
    elif total < ORDER_SIZE_LARGE_MAX_TOTAL:
        bucket = "large"
    else:
        bucket = "whale"

    event["_derived"] = {
        "item_count": item_count,
        "unique_products": unique_products,
        "avg_item_price": float(avg_price.quantize(Decimal("0.01"))),
        "order_size_bucket": bucket,
    }
    return event


def enrich_clickstream(event: dict) -> dict:
    """Add derived fields to a clickstream event.

    Adds:
    - is_mobile: viewport < 768px
    - page_category: derived from URL path
    - is_product_page: bool
    """
    viewport = event.get("viewport_width")
    page_url = event.get("page_url", "")

    if "/products/" in page_url:
        page_category = "product_detail"
        is_product_page = True
    elif "/cart" in page_url:
        page_category = "cart"
        is_product_page = False
    elif "/checkout" in page_url:
        page_category = "checkout"
        is_product_page = False
    elif "/search" in page_url:
        page_category = "search"
        is_product_page = False
    elif page_url == "/":
        page_category = "home"
        is_product_page = False
    else:
        page_category = "other"
        is_product_page = False

    event["_derived"] = {
        "is_mobile": viewport is not None and viewport < MOBILE_VIEWPORT_MAX_WIDTH,
        "page_category": page_category,
        "is_product_page": is_product_page,
    }
    return event


def compute_payment_risk_score(event: dict) -> dict:
    """Add a simple fraud risk score to payment events.

    Heuristic scoring (0.0 - 1.0):
    - High amount → higher risk
    - Bank transfer → lower risk than card
    - Missing user_id → higher risk
    """
    score = 0.0
    amount = float(event.get("amount", 0))

    if amount > PAYMENT_RISK_HIGH_AMOUNT_THRESHOLD:
        score += 0.3
    elif amount > PAYMENT_RISK_MEDIUM_AMOUNT_THRESHOLD:
        score += 0.1

    if event.get("method") == "card":
        score += 0.1
    elif event.get("method") == "wallet":
        score += 0.15

    if not event.get("user_id"):
        score += 0.3

    event["_derived"] = {
        "risk_score": min(score, 1.0),
        "risk_level": (
            "high"
            if score > PAYMENT_RISK_HIGH_SCORE_THRESHOLD
            else "medium"
            if score >= PAYMENT_RISK_MEDIUM_SCORE_THRESHOLD
            else "low"
        ),
    }
    return event
