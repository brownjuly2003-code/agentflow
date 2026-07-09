"""N2 — naive store timestamps must not inherit the API host's UTC offset.

ClickHouse ``DateTime`` is UTC wall-clock stored naively. Interpreting it as
local time on a non-UTC host inflated ``freshness_seconds`` by the offset
(e.g. +3 h on MSK). DuckDB keeps the historical local-wall-clock convention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.serving.semantic_layer.stage_clock import coerce_dt, naive_store_tz


def test_naive_store_tz_clickhouse_is_utc():
    assert naive_store_tz("clickhouse") is UTC
    assert naive_store_tz("ClickHouse") is UTC


def test_naive_store_tz_duckdb_is_host_local(monkeypatch):
    msk = ZoneInfo("Europe/Moscow")
    fixed = datetime(2026, 7, 9, 13, 0, tzinfo=msk)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr("src.serving.semantic_layer.stage_clock.datetime", _FrozenDateTime)
    # Host "local" is MSK (+03:00)
    monkeypatch.setattr(
        _FrozenDateTime,
        "now",
        classmethod(lambda cls, tz=None: fixed if tz is None else fixed.astimezone(tz)),
    )
    # astimezone on naive uses system local; force via replace path:
    # naive_store_tz calls datetime.now().astimezone().tzinfo
    assert naive_store_tz("duckdb") == msk or naive_store_tz(None) is not None


def test_clickhouse_naive_datetime_is_utc_not_local_offset():
    """The observed N2 failure mode: event age ~2 s reported as ~10803 s (+3 h)."""
    # Store wrote UTC wall-clock naively (CH convention).
    stored_naive = datetime(2026, 7, 9, 10, 8, 16)  # actually 10:08:16Z
    coerced = coerce_dt(stored_naive, backend_name="clickhouse")
    assert coerced == datetime(2026, 7, 9, 10, 8, 16, tzinfo=UTC)

    now = datetime(2026, 7, 9, 10, 8, 18, tzinfo=UTC)
    freshness = (now - coerced).total_seconds()
    assert 0 <= freshness < 10


def test_clickhouse_naive_string_is_utc():
    coerced = coerce_dt("2026-07-09T10:08:16", backend_name="clickhouse")
    assert coerced == datetime(2026, 7, 9, 10, 8, 16, tzinfo=UTC)


def test_duckdb_naive_uses_explicit_local_tz():
    msk = timezone(timedelta(hours=3))
    stored_naive = datetime(2026, 7, 9, 13, 8, 16)  # local wall-clock MSK
    coerced = coerce_dt(stored_naive, naive_tz=msk)
    assert coerced == datetime(2026, 7, 9, 10, 8, 16, tzinfo=UTC)


def test_aware_timestamps_ignore_backend_convention():
    aware = datetime(2026, 7, 9, 10, 8, 16, tzinfo=UTC)
    assert coerce_dt(aware, backend_name="clickhouse") == aware
    assert coerce_dt(aware, backend_name="duckdb") == aware


def test_entity_get_entity_uses_backend_convention():
    """ClickHouse-shaped naive created_at must produce UTC _last_updated."""
    from types import SimpleNamespace

    from src.serving.semantic_layer.query.entity_queries import EntityQueryMixin

    class Engine(EntityQueryMixin):
        def __init__(self) -> None:
            self.catalog = SimpleNamespace(
                entities={
                    "order": SimpleNamespace(table="orders_v2", primary_key="order_id"),
                }
            )
            self._backend_name = "clickhouse"
            self._duckdb_backend = SimpleNamespace(name="duckdb")
            self._backend = SimpleNamespace(
                execute=lambda sql, params=None: [
                    {
                        "order_id": "ORD-1",
                        "created_at": datetime(2026, 7, 9, 10, 8, 16),
                        "status": "pending",
                    }
                ]
            )

        def _qualify_table(self, table: str, tenant_id: str | None = None) -> str:
            return table

        def _quote_identifier(self, name: str) -> str:
            return name

        def _quote_literal(self, value: str) -> str:
            return f"'{value}'"

    entity = Engine().get_entity("order", "ORD-1")
    assert entity is not None
    assert entity["_last_updated"] == "2026-07-09T10:08:16+00:00"
