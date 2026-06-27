"""Unit tests for the DV2 OLTP->vault LISTEN/NOTIFY freshness mechanism (no Docker).

Two surfaces, both without a live database:

* ``freshness_listen_notify.sql`` installs one idempotent notify trigger per
  OLTP table, each emitting on the ``dv2_vault_refresh`` channel with the right
  branch argument and a ``clock_timestamp()`` emit time;
* the listener's pure core (``parse_notification`` / ``lag_ms`` /
  ``process_notifications``) promotes once per change event, skips foreign
  channels, and rejects malformed payloads.

A live trigger -> NOTIFY -> promote -> ``bv_order_canonical`` round-trip with a
measured lag is a separate single-node Mac smoke (see postgres_oltp/README.md),
mirroring the vault and writer smokes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from warehouse.agentflow.dv2.postgres_oltp import freshness_listener as fl
from warehouse.agentflow.dv2.postgres_oltp.freshness_listener import (
    CHANNEL,
    ChangeEvent,
    Measurement,
    db_now,
    lag_ms,
    parse_notification,
    process_notifications,
)

OLTP_DIR = Path(fl.__file__).resolve().parent
SQL = (OLTP_DIR / "freshness_listen_notify.sql").read_text(encoding="utf-8")
SQL_NO_COMMENTS = re.sub(r"--[^\n]*", "", SQL)  # comments mention now()/CH on purpose

OLTP_TABLES = [
    ("ops_msk.customers", "msk"),
    ("ops_msk.orders", "msk"),
    ("ops_dxb.customers", "dxb"),
    ("ops_dxb.orders", "dxb"),
]


# --- SQL structure -----------------------------------------------------------


def test_notify_function_emits_on_the_channel() -> None:
    assert "CREATE OR REPLACE FUNCTION rv.notify_oltp_change()" in SQL
    assert "pg_notify(" in SQL
    assert f"'{CHANNEL}'" in SQL  # the listener and the SQL agree on the channel


def test_emit_time_uses_clock_timestamp_not_now() -> None:
    # clock_timestamp() reflects the actual emit instant; now() would be the
    # transaction start and understate the lag.
    assert "clock_timestamp()" in SQL
    assert re.search(r"\bnow\(\)", SQL_NO_COMMENTS) is None


def test_one_idempotent_trigger_per_oltp_table() -> None:
    # DROP TRIGGER IF EXISTS before each CREATE TRIGGER makes re-apply safe.
    creates = re.findall(r"CREATE TRIGGER trg_notify_oltp_change", SQL)
    drops = re.findall(r"DROP TRIGGER IF EXISTS trg_notify_oltp_change", SQL)
    assert len(creates) == len(OLTP_TABLES)
    assert len(drops) == len(creates)


@pytest.mark.parametrize(("table", "branch"), OLTP_TABLES)
def test_trigger_fires_after_insert_or_update_with_branch_arg(table: str, branch: str) -> None:
    pattern = (
        rf"CREATE TRIGGER trg_notify_oltp_change AFTER INSERT OR UPDATE ON {re.escape(table)}\s+"
        rf"FOR EACH ROW EXECUTE FUNCTION rv\.notify_oltp_change\('{branch}'\)"
    )
    assert re.search(pattern, SQL), (
        f"missing/!= AFTER INSERT OR UPDATE trigger for {table} ({branch})"
    )


# --- parse_notification ------------------------------------------------------


def _payload(**over: object) -> str:
    base = {"branch": "msk", "source_table": "orders", "op": "INSERT", "emitted_at": 1000.5}
    base.update(over)
    return json.dumps(base)


def test_parse_notification_reads_all_fields() -> None:
    event = parse_notification(_payload())
    assert event == ChangeEvent(branch="msk", source_table="orders", op="INSERT", emitted_at=1000.5)


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps(
            {"branch": "msk", "source_table": "orders", "op": "INSERT"}
        ),  # missing emitted_at
        json.dumps(
            {"branch": "msk", "source_table": "orders", "op": "INSERT", "emitted_at": "soon"}
        ),
    ],
)
def test_parse_notification_rejects_malformed_payload(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_notification(bad)


# --- lag_ms ------------------------------------------------------------------


def test_lag_ms_is_milliseconds() -> None:
    event = parse_notification(_payload(emitted_at=1000.0))
    assert lag_ms(event, observed_at=1000.25) == pytest.approx(250.0)


def test_lag_ms_floors_at_zero_for_clock_skew() -> None:
    event = parse_notification(_payload(emitted_at=1000.0))
    assert lag_ms(event, observed_at=999.99) == 0.0


# --- process_notifications ---------------------------------------------------


def test_process_promotes_once_per_change_and_measures_lag() -> None:
    promoted: list[ChangeEvent] = []
    notes = [
        (CHANNEL, _payload(source_table="orders", emitted_at=10.0)),
        (CHANNEL, _payload(source_table="customers", emitted_at=11.0)),
    ]
    # `now` is sampled once per event (after promotion) -> deterministic lags.
    clock = iter([10.2, 11.05])
    out = process_notifications(notes, promoted.append, now=lambda: next(clock))

    assert [e.source_table for e in promoted] == ["orders", "customers"]
    assert isinstance(out[0], Measurement)
    assert out[0].lag_ms == pytest.approx(200.0)
    assert out[1].lag_ms == pytest.approx(50.0)


def test_process_skips_foreign_channels() -> None:
    promoted: list[ChangeEvent] = []
    notes = [
        ("some_other_channel", _payload()),
        (CHANNEL, _payload(source_table="orders")),
    ]
    out = process_notifications(notes, promoted.append, now=lambda: 1000.5)
    assert len(promoted) == 1
    assert len(out) == 1
    assert out[0].event.source_table == "orders"


def test_process_runs_idempotent_promotion_per_duplicate() -> None:
    # The promotion is idempotent (NOT EXISTS / ON CONFLICT, proven by smoke A),
    # so re-delivering the same change re-runs a safe no-op -- the listener does
    # not need to dedupe notifications itself.
    calls = 0

    def promote(_event: ChangeEvent) -> None:
        nonlocal calls
        calls += 1

    same = _payload(source_table="orders", emitted_at=5.0)
    process_notifications([(CHANNEL, same), (CHANNEL, same)], promote, now=lambda: 5.0)
    assert calls == 2


# --- db_now (skew-free observation clock) ------------------------------------


class _FakeClockCursor:
    def __init__(self, value: float) -> None:
        self._value = value

    def fetchone(self) -> tuple[float]:
        return (self._value,)


class _FakeClockConn:
    def __init__(self, value: float) -> None:
        self._value = value
        self.executed: str | None = None
        self.committed = False

    def execute(self, sql: str) -> _FakeClockCursor:
        self.executed = sql
        return _FakeClockCursor(self._value)

    def commit(self) -> None:
        self.committed = True


def test_db_now_reads_server_clock_and_commits() -> None:
    # The observation clock must be the PostgreSQL server clock (clock_timestamp),
    # not the client wall clock, or host/container skew swamps the lag.
    conn = _FakeClockConn(1717_000_000.5)
    value = db_now(conn)
    assert value == pytest.approx(1717_000_000.5)
    assert conn.executed is not None
    assert "clock_timestamp()" in conn.executed
    assert conn.committed is True
