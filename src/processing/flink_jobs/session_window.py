"""PyFlink-independent state transitions for the canonical session job."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any


def _tenant_id(event: Mapping[str, object]) -> str:
    return str(event.get("tenant") or event.get("tenant_id") or "default")


def session_key(event: Mapping[str, object]) -> str:
    session_id = event.get("session_id")
    if not session_id:
        raise ValueError("session_id is required for session aggregation")
    tenant_id = _tenant_id(event)
    return f"{tenant_id}\x1f{session_id}"


def raw_session_key(raw_event: str) -> str:
    return session_key(json.loads(raw_event))


def is_session_event(raw_event: str) -> bool:
    try:
        event = json.loads(raw_event)
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(event.get("session_id"))


def new_session(event: Mapping[str, object], event_ts: int) -> dict[str, Any]:
    return {
        "tenant_id": _tenant_id(event),
        "session_id": str(event["session_id"]),
        "user_id": event.get("user_id"),
        "first_event_ts": event_ts,
        "last_event_ts": event_ts,
        "event_count": 0,
        "pages": [],
        "has_add_to_cart": False,
        "has_checkout": False,
        "product_ids_viewed": [],
        "pages_truncated": False,
        "products_truncated": False,
    }


def accumulate_session(
    session: MutableMapping[str, Any],
    event: Mapping[str, object],
    event_ts: int,
    *,
    max_unique_pages: int,
    max_unique_products: int,
) -> None:
    """Apply one on-time event while keeping variable-sized state bounded."""
    session["first_event_ts"] = min(int(session["first_event_ts"]), event_ts)
    session["last_event_ts"] = max(int(session["last_event_ts"]), event_ts)
    session["event_count"] = int(session["event_count"]) + 1

    pages = session["pages"]
    page = event.get("page_url", "")
    if page and page not in pages:
        if len(pages) < max_unique_pages:
            pages.append(page)
        else:
            session["pages_truncated"] = True

    if event.get("event_type") == "add_to_cart":
        session["has_add_to_cart"] = True
    if "/checkout" in str(page):
        session["has_checkout"] = True

    products = session["product_ids_viewed"]
    product_id = event.get("product_id")
    if product_id and product_id not in products:
        if len(products) < max_unique_products:
            products.append(product_id)
        else:
            session["products_truncated"] = True


def summarize_session(session: Mapping[str, Any]) -> dict[str, object]:
    if session["has_checkout"]:
        funnel_stage = "checkout"
    elif session["has_add_to_cart"]:
        funnel_stage = "add_to_cart"
    elif session["product_ids_viewed"]:
        funnel_stage = "product_view"
    elif int(session["event_count"]) > 1:
        funnel_stage = "browse"
    else:
        funnel_stage = "bounce"

    first_event_ts = int(session["first_event_ts"])
    last_event_ts = int(session["last_event_ts"])
    return {
        "tenant_id": str(session.get("tenant_id") or "default"),
        "session_id": str(session["session_id"]),
        "user_id": session.get("user_id"),
        "started_at": datetime.fromtimestamp(first_event_ts / 1000, tz=UTC).isoformat(),
        "ended_at": datetime.fromtimestamp(last_event_ts / 1000, tz=UTC).isoformat(),
        "duration_seconds": (last_event_ts - first_event_ts) / 1000,
        "event_count": int(session["event_count"]),
        "unique_pages": len(session["pages"]),
        "products_viewed": len(session["product_ids_viewed"]),
        "funnel_stage": funnel_stage,
        "is_conversion": bool(session["has_checkout"]),
        "pages_truncated": bool(session.get("pages_truncated", False)),
        "products_truncated": bool(session.get("products_truncated", False)),
    }
