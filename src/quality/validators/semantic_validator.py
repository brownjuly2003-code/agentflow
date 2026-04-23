"""Semantic validation: business rules that go beyond schema correctness.

Schema validation checks structure. Semantic validation checks meaning:
- Does the order total actually match line items?
- Is the payment amount within reasonable bounds?
- Does the user_id reference a plausible user?

These rules catch data quality issues that pass schema validation
but would cause AI agents to give wrong answers.
"""

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class SemanticIssue:
    rule: str
    severity: str  # "error" | "warning"
    field: str
    message: str
    actual_value: str | None = None
    expected: str | None = None


@dataclass
class SemanticResult:
    event_id: str
    event_type: str
    is_clean: bool
    issues: list[SemanticIssue] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "is_clean": self.is_clean,
            "issues": [
                {
                    "rule": i.rule,
                    "severity": i.severity,
                    "field": i.field,
                    "message": i.message,
                }
                for i in self.issues
            ],
            "checked_at": self.checked_at.isoformat(),
        }


# ── Rule definitions ────────────────────────────────────────────


def _check_order_total_consistency(event: dict) -> list[SemanticIssue]:
    """Order total must match sum of (quantity * unit_price) for all items."""
    issues = []
    items = event.get("items", [])
    stated_total = Decimal(str(event.get("total_amount", 0)))

    computed_total = sum(
        Decimal(str(i.get("quantity", 0))) * Decimal(str(i.get("unit_price", 0))) for i in items
    )

    if abs(stated_total - computed_total) > Decimal("0.01"):
        issues.append(
            SemanticIssue(
                rule="order_total_consistency",
                severity="error",
                field="total_amount",
                message=f"Stated total {stated_total} != computed {computed_total}",
                actual_value=str(stated_total),
                expected=str(computed_total),
            )
        )
    return issues


def _check_payment_amount_bounds(event: dict) -> list[SemanticIssue]:
    """Payment amount should be between $0.50 and $50,000."""
    issues = []
    amount = Decimal(str(event.get("amount", 0)))

    if amount < Decimal("0.50"):
        issues.append(
            SemanticIssue(
                rule="payment_min_amount",
                severity="error",
                field="amount",
                message=f"Payment amount {amount} below minimum $0.50",
                actual_value=str(amount),
            )
        )
    elif amount > Decimal("50000"):
        issues.append(
            SemanticIssue(
                rule="payment_max_amount",
                severity="warning",
                field="amount",
                message=f"Payment amount {amount} exceeds $50,000 — needs manual review",
                actual_value=str(amount),
            )
        )
    return issues


def _check_payment_failure_reason(event: dict) -> list[SemanticIssue]:
    """Failed payments must have a failure_reason."""
    issues = []
    if event.get("status") == "failed" and not event.get("failure_reason"):
        issues.append(
            SemanticIssue(
                rule="payment_failure_reason_required",
                severity="warning",
                field="failure_reason",
                message="Failed payment missing failure_reason",
            )
        )
    return issues


def _check_clickstream_session_id(event: dict) -> list[SemanticIssue]:
    """Clickstream events must have a session_id."""
    issues = []
    if not event.get("session_id"):
        issues.append(
            SemanticIssue(
                rule="clickstream_session_required",
                severity="error",
                field="session_id",
                message="Clickstream event missing session_id",
            )
        )
    return issues


def _check_product_price_sanity(event: dict) -> list[SemanticIssue]:
    """Product price should be between $0 and $100,000."""
    issues = []
    price = Decimal(str(event.get("price", 0)))
    if price > Decimal("100000"):
        issues.append(
            SemanticIssue(
                rule="product_price_sanity",
                severity="warning",
                field="price",
                message=f"Product price {price} seems unreasonably high",
                actual_value=str(price),
            )
        )
    return issues


# ── Rule registry ───────────────────────────────────────────────

_RULES: dict[str, list] = {
    "order.": [_check_order_total_consistency],
    "payment.": [_check_payment_amount_bounds, _check_payment_failure_reason],
    "click": [_check_clickstream_session_id],
    "page_view": [_check_clickstream_session_id],
    "add_to_cart": [_check_clickstream_session_id],
    "product.": [_check_product_price_sanity],
}


def validate_semantics(event: dict) -> SemanticResult:
    """Run all applicable semantic rules on an event."""
    event_id = event.get("event_id", "unknown")
    event_type = event.get("event_type", "unknown")
    all_issues: list[SemanticIssue] = []

    for prefix, rules in _RULES.items():
        if event_type.startswith(prefix) or event_type == prefix:
            for rule_fn in rules:
                all_issues.extend(rule_fn(event))

    has_errors = any(i.severity == "error" for i in all_issues)

    return SemanticResult(
        event_id=event_id,
        event_type=event_type,
        is_clean=not has_errors,
        issues=all_issues,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run semantic validation checks")
    parser.add_argument("--check-all", action="store_true", help="Run all checks on sample data")
    args = parser.parse_args()

    if args.check_all:
        sample_order = {
            "event_id": "test-001",
            "event_type": "order.created",
            "total_amount": "100.00",
            "items": [{"quantity": 2, "unit_price": "50.00", "product_id": "P1"}],
        }
        result = validate_semantics(sample_order)
        print(f"Order check: is_clean={result.is_clean}, issues={len(result.issues)}")
