"""Tests for schema and semantic validators."""

import runpy
import sys
from pathlib import Path

from src.quality.validators.schema_validator import validate_batch, validate_event
from src.quality.validators.semantic_validator import validate_semantics

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    def test_valid_cdc_event(self):
        result = validate_event(
            {
                "event_id": "1d68d23f-f0a7-50f7-8fd3-ef6f8fd9a370",
                "event_type": "order.created",
                "operation": "insert",
                "timestamp": "2026-04-26T23:15:26.123000+00:00",
                "source": "postgres_cdc",
                "entity_type": "order",
                "entity_id": "ORD-CDC-1",
                "before": None,
                "after": {"order_id": "ORD-CDC-1"},
                "source_metadata": {
                    "connector": "postgresql",
                    "database": "agentflow_demo",
                    "schema": "public",
                    "table": "orders_v2",
                    "snapshot": "false",
                    "position": {"lsn": 26721944, "tx_id": 753},
                },
            }
        )

        assert result.is_valid

    def test_missing_fields(self):
        result = validate_event({"event_id": "test"})
        assert not result.is_valid

    def test_batch_validation(self, sample_order_event, sample_invalid_event):
        valid, failed = validate_batch([sample_order_event, sample_invalid_event])
        assert len(valid) == 1
        assert len(failed) == 1

    def test_validation_result_to_dict(self, sample_order_event):
        result = validate_event(sample_order_event)

        payload = result.to_dict()

        assert payload["is_valid"] is True
        assert payload["event_id"] == sample_order_event["event_id"]
        assert payload["event_type"] == sample_order_event["event_type"]
        assert payload["errors"] == []
        assert "T" in payload["validated_at"]

    def test_known_event_schema_errors_include_locations(self):
        result = validate_event({"event_id": "bad-order", "event_type": "order.created"})

        assert not result.is_valid
        assert result.event_id == "bad-order"
        assert result.errors
        assert all(isinstance(error["loc"], list) for error in result.errors)


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
        has_warning = any(i.rule == "payment_failure_reason_required" for i in result.issues)
        assert has_warning

    def test_clickstream_missing_session(self):
        event = {
            "event_id": "test-005",
            "event_type": "click",
        }
        result = validate_semantics(event)
        assert not result.is_clean

    def test_payment_above_maximum_is_warning_only(self):
        event = {
            "event_id": "test-006",
            "event_type": "payment.captured",
            "amount": "50000.01",
        }

        result = validate_semantics(event)

        assert result.is_clean
        assert result.issues[0].rule == "payment_max_amount"
        assert result.issues[0].severity == "warning"

    def test_product_price_sanity_warning(self):
        event = {
            "event_id": "test-007",
            "event_type": "product.updated",
            "price": "100001",
        }

        result = validate_semantics(event)

        assert result.is_clean
        assert result.issues[0].rule == "product_price_sanity"
        assert result.issues[0].severity == "warning"

    def test_semantic_result_to_dict(self):
        result = validate_semantics(
            {
                "event_id": "test-008",
                "event_type": "click",
            }
        )

        payload = result.to_dict()

        assert payload["event_id"] == "test-008"
        assert payload["event_type"] == "click"
        assert payload["is_clean"] is False
        assert payload["issues"][0]["rule"] == "clickstream_session_required"
        assert "T" in payload["checked_at"]

    def test_semantic_validator_check_all_cli_outputs_summary(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["semantic_validator.py", "--check-all"])

        runpy.run_path(
            str(PROJECT_ROOT / "src" / "quality" / "validators" / "semantic_validator.py"),
            run_name="__main__",
        )

        captured = capsys.readouterr()
        assert "Order check: is_clean=True, issues=0" in captured.out
