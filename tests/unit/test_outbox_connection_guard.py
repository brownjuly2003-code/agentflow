"""Unit tests for the OutboxProcessor connection lifecycle.

Covers the `_connection` property guard added when the outbox became a strict
mypy slice: the DuckDB handle is `DuckDBPyConnection | None` (nulled on close),
so reaching it through the property turns use-after-close into a loud
RuntimeError instead of an AttributeError on `None`.
"""

import pytest

from src.processing.outbox import OutboxProcessor


def test_process_pending_empty_returns_zero():
    processor = OutboxProcessor(duckdb_path=":memory:")
    try:
        assert processor.process_pending() == 0
    finally:
        processor.close()


def test_use_after_close_raises_runtime_error():
    processor = OutboxProcessor(duckdb_path=":memory:")
    processor.close()

    with pytest.raises(RuntimeError, match="connection is closed"):
        processor.process_pending()


def test_close_is_idempotent():
    processor = OutboxProcessor(duckdb_path=":memory:")
    processor.close()
    # A second close must not raise (owns_conn guard + None check).
    processor.close()
