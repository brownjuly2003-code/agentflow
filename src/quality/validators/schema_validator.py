"""Schema validation for incoming events.

Validates events against their Pydantic schemas before they enter the storage layer.
Returns structured validation results with error details for observability.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from src.ingestion.schemas.events import (
    CdcEvent,
    ClickstreamEvent,
    OrderEvent,
    PaymentEvent,
    ProductEvent,
)


@dataclass
class ValidationResult:
    is_valid: bool
    event_id: str
    event_type: str
    errors: list[dict] = field(default_factory=list)
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "errors": self.errors,
            "validated_at": self.validated_at.isoformat(),
        }


# Map event type prefixes to their Pydantic models
_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "order.": OrderEvent,
    "payment.": PaymentEvent,
    "click": ClickstreamEvent,
    "page_view": ClickstreamEvent,
    "add_to_cart": ClickstreamEvent,
    "product.": ProductEvent,
}

_CDC_SOURCES = {"postgres_cdc", "mysql_cdc"}


def _get_model_for_event(event_type: str) -> type[BaseModel] | None:
    for prefix, model in _SCHEMA_MAP.items():
        if event_type.startswith(prefix) or event_type == prefix:
            return model
    return None


def validate_event(raw_event: dict) -> ValidationResult:
    """Validate a single event against its schema.

    Args:
        raw_event: Raw event dict (already parsed from JSON).

    Returns:
        ValidationResult with is_valid=True if the event passes,
        or is_valid=False with structured error details.
    """
    event_id = raw_event.get("event_id", "unknown")
    event_type = raw_event.get("event_type", "unknown")

    model = CdcEvent if _is_cdc_event(raw_event) else _get_model_for_event(event_type)
    if model is None:
        return ValidationResult(
            is_valid=False,
            event_id=event_id,
            event_type=event_type,
            errors=[{"type": "unknown_event_type", "msg": f"No schema for: {event_type}"}],
        )

    try:
        model.model_validate(raw_event)
        return ValidationResult(is_valid=True, event_id=event_id, event_type=event_type)
    except ValidationError as e:
        errors = [
            {
                "type": err["type"],
                "loc": list(err["loc"]),
                "msg": err["msg"],
            }
            for err in e.errors()
        ]
        return ValidationResult(
            is_valid=False,
            event_id=event_id,
            event_type=event_type,
            errors=errors,
        )


def _is_cdc_event(raw_event: dict) -> bool:
    return (
        raw_event.get("source") in _CDC_SOURCES
        and "operation" in raw_event
        and "source_metadata" in raw_event
    )


def validate_batch(events: list[dict]) -> tuple[list[dict], list[ValidationResult]]:
    """Validate a batch of events. Returns (valid_events, failed_results)."""
    valid = []
    failed = []
    for event in events:
        result = validate_event(event)
        if result.is_valid:
            valid.append(event)
        else:
            failed.append(result)
    return valid, failed
