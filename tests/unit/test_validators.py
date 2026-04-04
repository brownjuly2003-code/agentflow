"""Tests for schema and semantic validators."""

from src.quality.validators.schema_validator import validate_batch, validate_event
from src.quality.validators.semantic_validator import validate_semantics


class TestSchemaValidator:
    def test_valid_order(self, sample_order_event):
        result = validate_event(sample_order_event)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_valid_payment(self, sample_payment_event):
        result = validate_event(sample_payment_event)
        assert result.is_valid

    def test_valid_click(self, sample_click_event):
        result = validate_event(sample_click_event)
        assert result.is_valid

    def test_unknown_event_type(self, sample_invalid_event):
        result = validate_event(sample_invalid_event)
        assert not result.is_valid
        assert result.errors[0]["type"] == "unknown_event_type"

    def test_missing_fields(self):
        result = validate_event({"event_id": "test"})
        assert not result.is_valid

    def test_batch_validation(self, sample_order_event, sample_invalid_event):
        valid, failed = validate_batch([sample_order_event, sample_invalid_event])
        assert len(valid) == 1
        assert len(failed) == 1


class TestSemanticValidator:
    def test_consistent_order_total(self):
        event = {
            "event_id": "test-001",
            "event_type": "order.created",
            "total_amount": "100.00",
            "items": [
                {"quantity": 2, "unit_price": "50.00"},
            ],
        }
        result = validate_semantics(event)
        assert result.is_clean

    def test_inconsistent_order_total(self):
        event = {
            "event_id": "test-002",
            "event_type": "order.created",
            "total_amount": "999.99",
            "items": [
                {"quantity": 1, "unit_price": "50.00"},
            ],
        }
        result = validate_semantics(event)
        assert not result.is_clean
        assert result.issues[0].rule == "order_total_consistency"

    def test_payment_below_minimum(self):
        event = {
            "event_id": "test-003",
            "event_type": "payment.initiated",
            "amount": "0.10",
        }
        result = validate_semantics(event)
        assert not result.is_clean
        assert result.issues[0].rule == "payment_min_amount"

    def test_failed_payment_without_reason(self):
        event = {
            "event_id": "test-004",
            "event_type": "payment.failed",
            "amount": "50.00",
            "status": "failed",
        }
        result = validate_semantics(event)
        has_warning = any(
            i.rule == "payment_failure_reason_required" for i in result.issues
        )
        assert has_warning

    def test_clickstream_missing_session(self):
        event = {
            "event_id": "test-005",
            "event_type": "click",
        }
        result = validate_semantics(event)
        assert not result.is_clean
