"""Usage accounting and session analytics on the embedded adapter (audit F-12).

`embedded_usage_audit.py` backs the default profile: the per-key usage counters
the admin surface bills and rate-limits from, and the session analytics behind
`/v1/admin/analytics/*`. Its PostgreSQL twin is exercised end to end by
`tests/integration/test_control_plane_postgres_live.py`; this file is the
embedded side of that parity, and it needs no server.

The expectations mirror the live suite's wherever the two adapters make the
same promise -- windows that actually exclude what falls outside them, tenant
scoping that does not leak a neighbour's traffic, and a QPS reading that stays
a reading rather than becoming an exception. Where the adapters differ they
differ on purpose, and the difference is stated in the test that pins it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from agentflow_runtime.serving.control_plane import (
    EmbeddedControlPlaneStore,
    ensure_api_sessions_table,
)
from agentflow_runtime.serving.control_plane.embedded_usage_audit import _window_to_interval
from agentflow_runtime.serving.control_plane.store import UsageRow


@pytest.fixture
def usage_db(tmp_path):
    return tmp_path / "usage.duckdb"


@pytest.fixture
def store(usage_db) -> EmbeddedControlPlaneStore:
    """A store whose usage and analytics tables both exist.

    The API's boot creates them once; the write methods deliberately do not
    create them on the hot path, so a test that skips this writes into a
    database with no tables.
    """
    instance = EmbeddedControlPlaneStore(usage_db_path_provider=lambda: usage_db)
    instance.ensure_usage_schema()
    connection = duckdb.connect(str(usage_db))
    try:
        ensure_api_sessions_table(connection)
    finally:
        connection.close()
    return instance


def _session(**overrides) -> dict:
    record = {
        "tenant": "acme",
        "key_name": "agent",
        "endpoint": "/v1/query",
        "method": "POST",
        "status_code": 200,
        "duration_ms": 10.0,
        "cache_hit": False,
        "entity_type": None,
        "entity_id": None,
        "metric_name": None,
        "query_engine": "duckdb",
        "query_text": None,
        "query_fingerprint": None,
    }
    record.update(overrides)
    return record


def _age(usage_db, request_id: str, *, by: timedelta) -> None:
    connection = duckdb.connect(str(usage_db))
    try:
        connection.execute(
            "UPDATE api_sessions SET ts = ? WHERE request_id = ?",
            [datetime.now(UTC) - by, request_id],
        )
    finally:
        connection.close()


# --- usage accounting --------------------------------------------------------


def test_usage_counts_group_by_tenant_within_the_last_day(store, usage_db) -> None:
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
    )
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
    )
    store.record_api_usage(
        tenant="beta", key_name="bot", endpoint="/v1/query", key_id="k2", key_slot="current"
    )
    connection = duckdb.connect(str(usage_db))
    try:
        # An older row is outside the 24h window the admin surface reports.
        connection.execute(
            "INSERT INTO api_usage (tenant, key_name, endpoint, ts, key_id, key_slot) "
            "VALUES ('acme', 'agent', '/v1/query', CURRENT_TIMESTAMP - INTERVAL 2 DAY, "
            "'k1', 'current')"
        )
    finally:
        connection.close()

    assert store.get_usage_by_tenant() == [
        {"tenant": "acme", "requests_last_24h": 2},
        {"tenant": "beta", "requests_last_24h": 1},
    ]
    assert store.get_usage_by_key() == {("acme", "agent"): 2, ("beta", "bot"): 1}


def test_old_key_usage_is_scoped_to_the_previous_slot_and_the_last_hour(store, usage_db) -> None:
    """Rotation reads this to answer "is anything still using the old key?".
    Counting the current slot, or an hour-old burst, would keep a rotation open
    that is actually finished."""
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="old-1", key_slot="previous"
    )
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="new-1", key_slot="current"
    )
    connection = duckdb.connect(str(usage_db))
    try:
        connection.execute(
            "INSERT INTO api_usage (tenant, key_name, endpoint, ts, key_id, key_slot) "
            "VALUES ('acme', 'agent', '/v1/query', CURRENT_TIMESTAMP - INTERVAL 2 HOUR, "
            "'old-2', 'previous')"
        )
        # key_id NULL: pre-rotation rows carry no id and cannot be attributed.
        connection.execute(
            "INSERT INTO api_usage (tenant, key_name, endpoint, ts, key_id, key_slot) "
            "VALUES ('acme', 'agent', '/v1/query', CURRENT_TIMESTAMP, NULL, 'previous')"
        )
    finally:
        connection.close()

    assert store.get_old_key_usage_by_key_id() == {"old-1": 1}


def test_a_usage_batch_lands_as_one_transaction(store) -> None:
    rows = [
        UsageRow(
            tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
        ),
        UsageRow(
            tenant="acme", key_name="agent", endpoint="/v1/entity", key_id="k1", key_slot="current"
        ),
        UsageRow(
            tenant="beta", key_name="bot", endpoint="/v1/query", key_id="k2", key_slot="current"
        ),
    ]

    store.record_api_usage_batch(rows)

    assert store.get_usage_by_key() == {("acme", "agent"): 2, ("beta", "bot"): 1}


def test_an_empty_usage_batch_is_a_no_op(store) -> None:
    # The writer flushes on a timer as well as on volume, so empty flushes are
    # routine and must not cost a transaction.
    store.record_api_usage_batch([])

    assert store.get_usage_by_tenant() == []


# --- session analytics -------------------------------------------------------


def test_usage_analytics_reports_error_and_cache_rates_per_tenant(store) -> None:
    store.record_api_session("r1", _session())
    store.record_api_session("r2", _session(status_code=500, cache_hit=True))
    store.record_api_session("r3", _session(tenant="beta", endpoint="/v1/entity"))

    analytics = store.get_usage_analytics(window="1h")

    assert analytics["window"] == "1h"
    acme = next(item for item in analytics["tenants"] if item["tenant"] == "acme")
    assert acme["total_requests"] == 2
    assert acme["error_rate"] == pytest.approx(0.5)
    assert acme["cache_hit_rate"] == pytest.approx(0.5)
    assert acme["top_endpoints"] == ["/v1/query"]
    assert acme["avg_duration_ms"] == pytest.approx(10.0)


def test_usage_analytics_can_be_scoped_to_one_tenant(store) -> None:
    store.record_api_session("r1", _session())
    store.record_api_session("r2", _session(tenant="beta"))

    scoped = store.get_usage_analytics(window="1h", tenant="beta")

    assert [item["tenant"] for item in scoped["tenants"]] == ["beta"]


def test_usage_analytics_excludes_what_falls_outside_the_window(store, usage_db) -> None:
    store.record_api_session("fresh", _session())
    store.record_api_session("stale", _session())
    _age(usage_db, "stale", by=timedelta(hours=3))

    analytics = store.get_usage_analytics(window="1h")

    assert analytics["tenants"][0]["total_requests"] == 1


def test_top_entities_counts_only_rows_that_named_one(store) -> None:
    store.record_api_session(
        "r1", _session(endpoint="/v1/entity/order/ORD-1", entity_type="order", entity_id="ORD-1")
    )
    store.record_api_session(
        "r2", _session(endpoint="/v1/entity/order/ORD-1", entity_type="order", entity_id="ORD-1")
    )
    store.record_api_session(
        "r3", _session(endpoint="/v1/entity/order/ORD-2", entity_type="order", entity_id="ORD-2")
    )
    store.record_api_session("r4", _session())  # /v1/query names no entity

    top = store.get_top_entities(window="1h")

    assert top["entities"] == [
        {"entity_type": "order", "entity_id": "ORD-1", "count": 2},
        {"entity_type": "order", "entity_id": "ORD-2", "count": 1},
    ]


def test_latency_analytics_reports_quantiles_per_endpoint(store) -> None:
    for index, duration in enumerate((10.0, 20.0, 30.0)):
        store.record_api_session(f"q{index}", _session(duration_ms=duration))
    store.record_api_session("e1", _session(endpoint="/v1/entity", duration_ms=5.0))

    latency = store.get_latency_analytics(window="1h")

    endpoints = {item["endpoint"]: item for item in latency["endpoints"]}
    assert endpoints["/v1/query"]["requests"] == 3
    assert endpoints["/v1/query"]["p50_ms"] == pytest.approx(20.0)
    assert endpoints["/v1/query"]["p95_ms"] == pytest.approx(30.0, abs=1.0)
    assert endpoints["/v1/entity"]["p50_ms"] == pytest.approx(5.0)


def test_anomalies_flag_a_tenant_whose_current_hour_spikes(store, usage_db) -> None:
    """The rule is current hour over the average of its own earlier hours,
    above 3x. One quiet hour then a burst is the shape an operator wants
    paged about."""
    for index in range(2):
        store.record_api_session(f"past-{index}", _session())
        _age(usage_db, f"past-{index}", by=timedelta(hours=index + 1))
    for index in range(6):
        store.record_api_session(f"now-{index}", _session())

    anomalies = store.get_anomalies(window="24h")

    assert [item["tenant"] for item in anomalies["anomalies"]] == ["acme"]
    assert anomalies["anomalies"][0]["current_hour_requests"] == 6
    assert anomalies["anomalies"][0]["spike_ratio"] > 3


def test_steady_traffic_is_not_an_anomaly(store, usage_db) -> None:
    for index in range(3):
        store.record_api_session(f"past-{index}", _session())
        _age(usage_db, f"past-{index}", by=timedelta(hours=index + 1))
    store.record_api_session("now", _session())

    assert store.get_anomalies(window="24h")["anomalies"] == []


def test_queries_per_second_counts_the_last_minute(store, usage_db) -> None:
    for index in range(6):
        store.record_api_session(f"r{index}", _session())
    store.record_api_session("older", _session())
    _age(usage_db, "older", by=timedelta(minutes=5))

    assert store.get_queries_per_second_last_minute() == pytest.approx(0.1)


def test_queries_per_second_degrades_to_zero_when_the_read_fails(store, monkeypatch) -> None:
    """`/health` and the ops dashboard read this. A read that cannot answer
    reports no traffic rather than taking the caller down with it -- the same
    contract the PostgreSQL adapter is held to when its server is
    unreachable."""

    class _BrokenConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, *args, **kwargs):
            raise duckdb.Error("usage db is unavailable")

        def close(self) -> None:
            self.closed = True

    connection = _BrokenConnection()
    monkeypatch.setattr(store, "_usage_cursor", lambda: connection)

    assert store.get_queries_per_second_last_minute() == 0.0
    assert connection.closed is True  # the failing read still returns the handle


def test_a_store_that_cannot_open_at_all_stays_visible(store, monkeypatch) -> None:
    # The zero above is a guard around the *read*, deliberately not around the
    # connect: a usage database that cannot be opened is a different failure
    # and must not be reported as "no traffic".
    def _broken_cursor():
        raise duckdb.Error("usage db is unavailable")

    monkeypatch.setattr(store, "_usage_cursor", _broken_cursor)

    with pytest.raises(duckdb.Error):
        store.get_queries_per_second_last_minute()


# --- windows -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "interval"),
    [("15m", "15 minutes"), ("1h", "1 hours"), ("7d", "7 days")],
)
def test_window_shorthands_become_intervals(window: str, interval: str) -> None:
    assert _window_to_interval(window) == interval


@pytest.mark.parametrize("window", ["", "1", "h", "1w", "-1h", "1 h", "abc"])
def test_an_unparseable_window_is_refused(window: str) -> None:
    # The window arrives from an admin query string; refusing it keeps a typo
    # from silently widening or narrowing what an operator thinks they asked.
    with pytest.raises(ValueError, match="Invalid window"):
        _window_to_interval(window)


# --- lock contention and the paths taken under it ----------------------------
#
# Audit F-12: every branch below was unexercised, and each one decides what
# happens when DuckDB refuses a handle -- whether accounting is retried, moved,
# lost loudly, or lost silently. They are also the only paths where a request
# thread and the analytics writer can collide, which is what made them worth
# writing rather than counting.


class _FlakyCursor:
    """Raises `duckdb.Error` for the first `failures` calls, then delegates.

    Injected in place of `_usage_cursor`, which is the seam every retry loop in
    the repository turns on.
    """

    def __init__(self, store, failures: int, error: type[Exception] = duckdb.Error) -> None:
        self._store = store
        self._remaining = failures
        self._error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error("database is locked")
        return type(self._store)._usage_cursor(self._store)


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """The retry loops sleep 10ms x attempt. Real time adds nothing here."""
    monkeypatch.setattr(
        "agentflow_runtime.serving.control_plane.embedded_usage_audit.time.sleep",
        lambda _seconds: None,
    )


def test_a_transient_lock_is_retried_rather_than_dropped(store, monkeypatch) -> None:
    flaky = _FlakyCursor(store, failures=3)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
    )

    assert flaky.calls == 4  # three refusals, then the write
    assert store.get_usage_by_tenant() == [{"tenant": "acme", "requests_last_24h": 1}]


def test_usage_accounting_gives_up_loudly_after_ten_attempts(store, monkeypatch) -> None:
    """Usage accounting is billing and rate-limit input. When it cannot be
    written at all the caller has to know -- unlike analytics below, which is
    allowed to be lost."""
    flaky = _FlakyCursor(store, failures=99)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    with pytest.raises(duckdb.Error):
        store.record_api_usage(
            tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
        )

    assert flaky.calls == 10


def test_a_batch_retries_and_still_lands_exactly_once(store, monkeypatch) -> None:
    flaky = _FlakyCursor(store, failures=2)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    store.record_api_usage_batch(
        [
            UsageRow(
                tenant="acme",
                key_name="agent",
                endpoint="/v1/query",
                key_id="k1",
                key_slot="current",
            ),
        ]
    )

    # The retry restarts the whole transaction, so the row is written once, not
    # once per attempt.
    assert store.get_usage_by_key() == {("acme", "agent"): 1}


def test_a_failed_batch_rolls_back_and_raises(store, monkeypatch) -> None:
    """The batch is one transaction on purpose (docs/perf/usage-write-
    bifurcation-2026-07-09.md). A partially applied flush would double-count
    the rows the writer re-sends."""

    class _RollbackWatcher:
        def __init__(self, real):
            self._real = real
            self.statements: list[str] = []

        def execute(self, sql, *args, **kwargs):
            self.statements.append(sql.strip().split()[0].upper())
            return self._real.execute(sql, *args, **kwargs)

        def executemany(self, *args, **kwargs):
            raise duckdb.Error("insert failed mid-batch")

        def close(self):
            self._real.close()

    real = store._usage_cursor()
    watcher = _RollbackWatcher(real)
    monkeypatch.setattr(store, "_usage_cursor", lambda: watcher)

    with pytest.raises(duckdb.Error):
        store.record_api_usage_batch(
            [
                UsageRow(
                    tenant="acme",
                    key_name="agent",
                    endpoint="/v1/query",
                    key_id="k1",
                    key_slot="current",
                )
            ]
        )

    assert "ROLLBACK" in watcher.statements
    assert "COMMIT" not in watcher.statements


def test_reads_retry_the_same_way_writes_do(store, monkeypatch) -> None:
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="old-1", key_slot="previous"
    )
    flaky = _FlakyCursor(store, failures=2)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    assert store.get_usage_by_key() == {("acme", "agent"): 1}

    flaky_old_key = _FlakyCursor(store, failures=2)
    monkeypatch.setattr(store, "_usage_cursor", flaky_old_key)

    assert store.get_old_key_usage_by_key_id() == {"old-1": 1}


def test_analytics_is_dropped_quietly_when_the_database_stays_locked(store, monkeypatch) -> None:
    """The opposite call on the same failure: a session record is telemetry
    written from a background task, so ten refusals end in a log line, not an
    exception that would surface on a request that already succeeded."""
    flaky = _FlakyCursor(store, failures=99)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    store.record_api_session("r1", _session())  # must not raise

    assert flaky.calls == 10


def test_schema_setup_retries_a_locked_database(store, monkeypatch) -> None:
    flaky = _FlakyCursor(store, failures=3)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    store.ensure_usage_schema()

    assert flaky.calls == 4


def test_schema_setup_reraises_for_a_configured_path(tmp_path, monkeypatch) -> None:
    """The fallback below exists for the default database only. When an
    operator named the path, moving their data somewhere else silently would
    be worse than failing."""
    monkeypatch.delenv("AGENTFLOW_USAGE_DB_PATH", raising=False)
    configured = tmp_path / "operator-chosen.duckdb"
    store = EmbeddedControlPlaneStore(usage_db_path_provider=lambda: configured)
    flaky = _FlakyCursor(store, failures=99, error=duckdb.IOException)
    monkeypatch.setattr(store, "_usage_cursor", flaky)

    with pytest.raises(duckdb.IOException):
        store.ensure_usage_schema()

    assert store._usage_db_path_override is None


def test_the_default_database_falls_back_to_a_private_file_when_locked(
    tmp_path, monkeypatch
) -> None:
    """Windows will not let a second process open the default
    `agentflow_api.duckdb`, and an API that refuses to boot because another
    copy is running is worse than one whose usage counters are process-local.
    The fallback is sticky: the store keeps writing to the file it landed on.
    """
    monkeypatch.delenv("AGENTFLOW_USAGE_DB_PATH", raising=False)
    monkeypatch.setenv("TEMP", str(tmp_path))
    store = EmbeddedControlPlaneStore(
        usage_db_path_provider=lambda: tmp_path / "agentflow_api.duckdb"
    )
    original_cursor = type(store)._usage_cursor

    def locked_until_moved():
        if store._usage_db_path_override is None:
            raise duckdb.IOException("file is locked by another process")
        return original_cursor(store)

    monkeypatch.setattr(store, "_usage_cursor", locked_until_moved)

    store.ensure_usage_schema()

    override = store._usage_db_path_override
    assert override is not None
    assert override.parent == tmp_path
    assert override.name.startswith("agentflow_api_")
    # And the schema really landed there, so accounting continues.
    store.record_api_usage(
        tenant="acme", key_name="agent", endpoint="/v1/query", key_id="k1", key_slot="current"
    )
    assert store.get_usage_by_tenant() == [{"tenant": "acme", "requests_last_24h": 1}]
