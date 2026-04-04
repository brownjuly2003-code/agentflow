"""Tests for event enrichment functions."""

from src.processing.transformations.enrichment import (
    compute_payment_risk_score,
    enrich_clickstream,
    enrich_order,
)


class TestEnrichOrder:
    def test_basic_enrichment(self, sample_order_event):
        result = enrich_order(sample_order_event)
        derived = result["_derived"]

        assert derived["item_count"] == 3  # 2 + 1
        assert derived["unique_products"] == 2
        assert derived["order_size_bucket"] == "large"
        assert derived["avg_item_price"] > 0

    def test_small_order_bucket(self):
        event = {
            "items": [{"product_id": "P1", "quantity": 1, "unit_price": "9.99"}],
            "total_amount": "9.99",
        }
        result = enrich_order(event)
        assert result["_derived"]["order_size_bucket"] == "small"

    def test_whale_order_bucket(self):
        event = {
            "items": [{"product_id": "P1", "quantity": 10, "unit_price": "200.00"}],
            "total_amount": "2000.00",
        }
        result = enrich_order(event)
        assert result["_derived"]["order_size_bucket"] == "whale"

    def test_empty_items(self):
        event = {"items": [], "total_amount": "0"}
        result = enrich_order(event)
        assert result["_derived"]["item_count"] == 0
        assert result["_derived"]["unique_products"] == 0


class TestEnrichClickstream:
    def test_product_page(self):
        event = {"page_url": "/products/PROD-001", "viewport_width": 1440}
        result = enrich_clickstream(event)
        derived = result["_derived"]

        assert derived["page_category"] == "product_detail"
        assert derived["is_product_page"] is True
        assert derived["is_mobile"] is False

    def test_mobile_detection(self):
        event = {"page_url": "/", "viewport_width": 375}
        result = enrich_clickstream(event)
        assert result["_derived"]["is_mobile"] is True

    def test_checkout_page(self):
        event = {"page_url": "/checkout", "viewport_width": 1024}
        result = enrich_clickstream(event)
        assert result["_derived"]["page_category"] == "checkout"
        assert result["_derived"]["is_product_page"] is False

    def test_null_viewport(self):
        event = {"page_url": "/search", "viewport_width": None}
        result = enrich_clickstream(event)
        assert result["_derived"]["is_mobile"] is False


class TestPaymentRiskScore:
    def test_low_risk(self):
        event = {"amount": 50, "method": "bank_transfer", "user_id": "USR-123"}
        result = compute_payment_risk_score(event)
        assert result["_derived"]["risk_level"] == "low"

    def test_high_risk_large_amount_no_user(self):
        event = {"amount": 600, "method": "wallet", "user_id": None}
        result = compute_payment_risk_score(event)
        assert result["_derived"]["risk_level"] == "high"
        assert result["_derived"]["risk_score"] <= 1.0

    def test_medium_risk(self):
        event = {"amount": 250, "method": "card", "user_id": "USR-123"}
        result = compute_payment_risk_score(event)
        assert result["_derived"]["risk_level"] == "medium"
