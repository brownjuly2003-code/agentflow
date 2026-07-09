"""Usage accounting must not pace the request it is counting.

The write used to happen inline (later: on a worker thread) before the response
was produced. The embedded store serializes writers and commits per row, so a
slow disk turned every authenticated request into a queue on one fsync. The CI
``Load Test`` collapsed onto a saturated branch pinned at ``rps = 1/commit``,
which three red runs hit within 1.7% of each other while green runs spread
across 37-46 rps. Full measurement:
``docs/perf/usage-write-bifurcation-2026-07-09.md``.

These tests pin the *guarantee* — the response does not wait on the write, and
a write that fails or is shed still serves the request — not the mechanism.

They subsume ``test_auth_usage_write_failure.py``, which guarded the same
side-channel promise from the other direction: a `BinderException` out of the
usage write used to escape `AuthMiddleware` and turn a served request into a
500 (all six endpoints, Load Test of 2026-07-09). That test drove the failure
through `AuthManager.record_usage`, which the request path no longer calls, so
it pinned a call that no longer exists. The promise it guarded is
`test_request_succeeds_when_the_usage_write_raises` below.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, build_auth_middleware
from src.serving.api.metrics import USAGE_RECORD_FAILURES, USAGE_ROWS_DROPPED

API_KEY = "tenant-order-key"
SLOW_WRITE_SECONDS = 0.4


def _build_app(tmp_path: Path) -> FastAPI:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        f"""
keys:
  - key: "{API_KEY}"
    name: "Order Agent"
    tenant: "acme"
    rate_limit_rpm: 1000
    created_at: "2026-04-10"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    app = FastAPI()
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    manager.load()
    manager.ensure_usage_table()
    app.state.auth_manager = manager
    app.middleware("http")(build_auth_middleware())

    @app.get("/v1/metrics/revenue")
    async def revenue():
        return {"metric_name": "revenue", "value": 100.0}

    return app


def _failures() -> float:
    return USAGE_RECORD_FAILURES._value.get()


def _dropped() -> float:
    return USAGE_ROWS_DROPPED._value.get()


def test_a_slow_usage_write_does_not_delay_the_response(tmp_path: Path) -> None:
    """The defect, stated as a test: with the write inline this request took
    at least SLOW_WRITE_SECONDS; off the path it returns immediately."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager
    entered = threading.Event()

    def slow_batch(rows):
        entered.set()
        time.sleep(SLOW_WRITE_SECONDS)

    manager.store.record_api_usage_batch = slow_batch  # type: ignore[method-assign]

    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert entered.wait(2.0), "the writer thread never picked the row up"
    assert elapsed < SLOW_WRITE_SECONDS / 2, (
        f"the response waited {elapsed:.3f}s on a {SLOW_WRITE_SECONDS}s usage write"
    )
    manager.close_usage_writer()


def test_request_succeeds_when_the_usage_write_raises(tmp_path: Path) -> None:
    """A store that exhausts its retries loses the row and counts it. The
    request it was counting is served regardless."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager

    def exploding_batch(rows):
        raise duckdb.BinderException(
            'Unique file handle conflict: Cannot attach "agentflow-api-usage"'
        )

    manager.store.record_api_usage_batch = exploding_batch  # type: ignore[method-assign]

    before = _failures()
    with TestClient(app) as client:
        response = client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})
        assert response.status_code == 200
        assert response.json() == {"metric_name": "revenue", "value": 100.0}
        assert manager.flush_usage(timeout=5.0)

    assert _failures() == before + 1
    manager.close_usage_writer()


def test_healthy_request_does_not_touch_the_failure_counter(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    manager = app.state.auth_manager

    before = _failures()
    with TestClient(app) as client:
        response = client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})
        assert response.status_code == 200
        assert manager.flush_usage(timeout=5.0)

    assert _failures() == before
    manager.close_usage_writer()


def test_a_failed_batch_publishes_no_audit_event(tmp_path: Path) -> None:
    """A publish must never claim a row that was never inserted — the
    invariant the old synchronous `record_usage` got from the raise."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager
    published: list[dict] = []

    class Recorder:
        def publish(self, payload: dict) -> None:
            published.append(payload)

    manager._usage_writer._audit_publisher = Recorder()

    def exploding_batch(rows):
        raise duckdb.IOException("disk gone")

    manager.store.record_api_usage_batch = exploding_batch  # type: ignore[method-assign]

    with TestClient(app) as client:
        assert client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY}).status_code == 200
        assert manager.flush_usage(timeout=5.0)

    assert published == []
    manager.close_usage_writer()


def test_rows_are_durable_after_flush(tmp_path: Path) -> None:
    """Read-your-writes: the admin usage read flushes the queue first."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager

    with TestClient(app) as client:
        for _ in range(5):
            assert (
                client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY}).status_code == 200
            )
        usage = manager.usage_by_tenant()

    assert usage == [{"tenant": "acme", "requests_last_24h": 5}]
    manager.close_usage_writer()


def test_a_full_queue_sheds_the_row_and_serves_the_request(tmp_path: Path) -> None:
    """Backpressure is bounded and never blocking: the counter moves, the
    client does not wait."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager
    release = threading.Event()

    def blocking_batch(rows):
        release.wait(5.0)

    manager.store.record_api_usage_batch = blocking_batch  # type: ignore[method-assign]
    # One slot: the first row occupies the writer, the second fills the queue,
    # the third has nowhere to go.
    manager._usage_writer._queue.maxsize = 1

    before = _dropped()
    with TestClient(app) as client:
        for _ in range(4):
            assert (
                client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY}).status_code == 200
            )

    assert _dropped() > before
    release.set()
    manager.close_usage_writer()


def test_batching_coalesces_rows_into_one_commit(tmp_path: Path) -> None:
    """The writer must batch, or it just moves the 1/commit ceiling into a
    queue that silently overflows."""
    app = _build_app(tmp_path)
    manager = app.state.auth_manager
    batches: list[int] = []
    gate = threading.Event()

    real = manager.store.record_api_usage_batch

    def counting_batch(rows):
        gate.wait(2.0)
        batches.append(len(rows))
        return real(rows)

    manager.store.record_api_usage_batch = counting_batch  # type: ignore[method-assign]

    rows_submitted = 24
    with TestClient(app) as client:
        for _ in range(rows_submitted):
            client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})
        # Everything queued behind the gate; releasing it lets one drain pick
        # up the whole backlog in a single batch.
        gate.set()
        assert manager.flush_usage(timeout=5.0)

    assert sum(batches) == rows_submitted
    assert max(batches) > 1, f"no coalescing happened: {batches}"
    assert len(batches) < rows_submitted, f"one commit per row: {batches}"
    manager.close_usage_writer()


@pytest.mark.parametrize("rows", [0, 1, 7])
def test_batch_write_is_atomic_and_complete(tmp_path: Path, rows: int) -> None:
    """The DuckDB override wraps the batch in one transaction; every row lands."""
    from src.serving.control_plane.embedded import EmbeddedControlPlaneStore
    from src.serving.control_plane.store import UsageRow

    usage_db = tmp_path / f"usage-{rows}.duckdb"
    store = EmbeddedControlPlaneStore(usage_db_path_provider=lambda: usage_db)
    store.ensure_usage_schema()
    store.record_api_usage_batch(
        [
            UsageRow(
                tenant="acme",
                key_name="Order Agent",
                endpoint="/v1/metrics/revenue",
                key_id=f"k{i}",
                key_slot="current",
            )
            for i in range(rows)
        ]
    )
    usage = store.get_usage_by_tenant()
    assert usage == ([] if rows == 0 else [{"tenant": "acme", "requests_last_24h": rows}])
