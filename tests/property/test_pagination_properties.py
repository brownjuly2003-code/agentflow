import base64
import hashlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

_QUERY_HASH_STRATEGY = st.binary(min_size=1, max_size=32).map(
    lambda value: hashlib.sha256(value).hexdigest()
)
_INVALID_CURSOR_PAYLOADS = st.one_of(
    st.text(min_size=1, max_size=32).filter(lambda value: ":" not in value),
    st.integers(max_value=-1).map(lambda value: f"{value}:hash"),
    st.text(min_size=0, max_size=5).map(lambda value: f"{value}:"),
)


def _build_engine() -> QueryEngine:
    return QueryEngine(DataCatalog())


@given(offset=st.integers(min_value=0, max_value=10_000), query_hash=_QUERY_HASH_STRATEGY)
def test_cursor_roundtrip(offset: int, query_hash: str) -> None:
    engine = _build_engine()
    cursor = engine._encode_cursor(offset, query_hash)

    decoded_offset, decoded_hash = engine._decode_cursor(cursor)

    assert decoded_offset == offset
    assert decoded_hash == query_hash


@given(payload=_INVALID_CURSOR_PAYLOADS)
def test_invalid_cursor_payloads_raise_value_error(payload: str) -> None:
    engine = _build_engine()
    cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    with pytest.raises(ValueError, match="Invalid cursor value"):
        engine._decode_cursor(cursor)


@given(limit=st.integers(min_value=1, max_value=12))
def test_paginated_query_never_returns_more_than_limit(limit: int) -> None:
    engine = _build_engine()
    result = engine.paginated_query("Show me top 10 products", limit=limit)

    assert len(result["data"]) <= limit
    assert result["row_count"] == len(result["data"])
    assert result["page_size"] == limit
    assert (result["next_cursor"] is not None) is result["has_more"]


@given(limit=st.integers(min_value=1, max_value=9))
def test_cursor_cannot_be_reused_for_different_queries(limit: int) -> None:
    engine = _build_engine()
    first_page = engine.paginated_query("Show me top 10 products", limit=limit)

    with pytest.raises(ValueError, match="Cursor does not match"):
        engine.paginated_query(
            "What is total revenue today",
            limit=limit,
            cursor=first_page["next_cursor"],
        )
