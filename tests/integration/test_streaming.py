"""Integration tests for the SSE streaming endpoint."""

import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.serving.api.auth import TenantKey, build_auth_middleware
from src.serving.api.main import app
from src.serving.api.routers import stream as stream_router


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class _ReceiveChannel:
    def __init__(self) -> None:
        self._sent_request = False
        self._disconnected = asyncio.Event()

    async def __call__(self):
        if not self._sent_request:
            self._sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnected.wait()
        return {"type": "http.disconnect"}

    def disconnect(self) -> None:
        self._disconnected.set()


def _prepare_stream_events(client: TestClient, tenant_id: str = "default") -> None:
    conn = client.app.state.query_engine._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}

    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN tenant_id VARCHAR DEFAULT 'default'")
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")

    conn.execute("DELETE FROM pipeline_events")
    conn.execute(
        """
        INSERT INTO pipeline_events (
            event_id, topic, processed_at, event_type, entity_id, latency_ms, tenant_id
        )
        VALUES
            (
                'evt-order-1', 'events.validated', NOW() - INTERVAL '4 seconds',
                'order.created', 'ORD-1', 15, ?
            ),
            (
                'evt-payment-1', 'events.validated', NOW() - INTERVAL '3 seconds',
                'payment.initiated', 'ORD-1', 20, ?
            ),
            (
                'evt-click-1', 'events.validated', NOW() - INTERVAL '2 seconds',
                'page_view', 'USR-1', 5, ?
            ),
            (
                'evt-order-2', 'events.validated', NOW() - INTERVAL '1 seconds',
                'order.shipped', 'ORD-2', 12, ?
            )
    """,
        [tenant_id, tenant_id, tenant_id, tenant_id],
    )


def _prepare_cross_tenant_stream_events(client: TestClient) -> None:
    conn = client.app.state.query_engine._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN tenant_id VARCHAR DEFAULT 'default'")
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")

    conn.execute("DELETE FROM pipeline_events")
    conn.execute("""
        INSERT INTO pipeline_events (
            event_id, topic, processed_at, event_type, entity_id, latency_ms, tenant_id
        )
        VALUES
            (
                'evt-acme-stream', 'events.validated', NOW() - INTERVAL '2 seconds',
                'order.created', 'ORD-ACME', 15, 'acme'
            ),
            (
                'evt-beta-stream', 'events.validated', NOW() - INTERVAL '1 seconds',
                'order.created', 'ORD-BETA', 15, 'beta'
            )
    """)


def _disable_auth(client: TestClient, monkeypatch) -> None:
    manager = client.app.state.auth_manager
    monkeypatch.setattr(manager, "keys_by_value", {})
    manager._rate_windows.clear()
    # Auth fail-closed default in middleware needs an explicit opt-out for tests.
    monkeypatch.setattr(client.app.state, "auth_disabled", True, raising=False)


def _build_stream_request(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    event_type: str | None = None,
    entity_id: str | None = None,
) -> tuple[Request, _ReceiveChannel]:
    params = {
        key: value
        for key, value in {
            "event_type": event_type,
            "entity_id": entity_id,
        }.items()
        if value is not None
    }
    header_items = [(b"host", b"testserver")]
    if headers:
        header_items.extend(
            (name.lower().encode(), value.encode()) for name, value in headers.items()
        )

    receive = _ReceiveChannel()
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/stream/events",
            "raw_path": b"/v1/stream/events",
            "query_string": urlencode(params).encode(),
            "headers": header_items,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": client.app,
        },
        receive=receive,
    )
    return request, receive


async def _dispatch_stream_request(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    event_type: str | None = None,
    entity_id: str | None = None,
):
    request, receive = _build_stream_request(
        client,
        headers=headers,
        event_type=event_type,
        entity_id=entity_id,
    )
    middleware = build_auth_middleware()

    async def call_next(inner_request: Request):
        return await stream_router.stream_events(
            request=inner_request,
            event_type=event_type,
            entity_id=entity_id,
        )

    response = await middleware(request, call_next)
    return response, receive


async def _first_sse_payload(response) -> dict:
    chunk = await asyncio.wait_for(anext(response.body_iterator), timeout=2)
    frame = chunk.decode() if isinstance(chunk, bytes) else chunk
    for line in frame.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise AssertionError("SSE stream did not yield a data frame")


@pytest.mark.integration
class TestStreamingAPI:
    @pytest.mark.asyncio
    async def test_stream_events_returns_sse_response(self, client, monkeypatch):
        _prepare_stream_events(client)
        _disable_auth(client, monkeypatch)

        response, receive = await _dispatch_stream_request(client)
        assert response.status_code == 200
        assert response.media_type == "text/event-stream"

        payload = await _first_sse_payload(response)

        receive.disconnect()
        await response.body_iterator.aclose()

        assert payload["event_id"] == "evt-order-1"
        assert payload["event_type"] == "order.created"
        assert payload["entity_id"] == "ORD-1"

    @pytest.mark.asyncio
    async def test_stream_events_filters_by_event_type(self, client, monkeypatch):
        _prepare_stream_events(client)
        _disable_auth(client, monkeypatch)

        response, receive = await _dispatch_stream_request(client, event_type="order")
        payload = await _first_sse_payload(response)

        receive.disconnect()
        await response.body_iterator.aclose()

        assert payload["event_type"].startswith("order.")

    @pytest.mark.asyncio
    async def test_stream_events_filters_by_entity_id(self, client, monkeypatch):
        _prepare_stream_events(client)
        _disable_auth(client, monkeypatch)

        response, receive = await _dispatch_stream_request(client, entity_id="ORD-2")
        payload = await _first_sse_payload(response)

        receive.disconnect()
        await response.body_iterator.aclose()

        assert payload["entity_id"] == "ORD-2"
        assert payload["event_id"] == "evt-order-2"

    @pytest.mark.asyncio
    async def test_stream_events_require_api_key_when_auth_enabled(self, client, monkeypatch):
        _prepare_stream_events(client, tenant_id="acme")

        manager = client.app.state.auth_manager
        monkeypatch.setattr(
            manager,
            "keys_by_value",
            {
                "stream-test-key": TenantKey(
                    key="stream-test-key",
                    name="stream-tester",
                    tenant="acme",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                )
            },
        )
        manager._rate_windows.clear()

        unauthorized_response, _ = await _dispatch_stream_request(client)
        assert unauthorized_response.status_code == 401

        authorized_response, receive = await _dispatch_stream_request(
            client,
            headers={"X-API-Key": "stream-test-key"},
        )
        assert authorized_response.status_code == 200

        payload = await _first_sse_payload(authorized_response)

        receive.disconnect()
        await authorized_response.body_iterator.aclose()

        assert payload["event_id"] == "evt-order-1"

    @pytest.mark.asyncio
    async def test_stream_filters_by_tenant_id(self, client, monkeypatch):
        _prepare_cross_tenant_stream_events(client)

        manager = client.app.state.auth_manager
        monkeypatch.setattr(
            manager,
            "keys_by_value",
            {
                "acme-stream-key": TenantKey(
                    key="acme-stream-key",
                    name="acme-streamer",
                    tenant="acme",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                ),
                "beta-stream-key": TenantKey(
                    key="beta-stream-key",
                    name="beta-streamer",
                    tenant="beta",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                ),
            },
        )
        manager._rate_windows.clear()

        response, receive = await _dispatch_stream_request(
            client,
            headers={"X-API-Key": "acme-stream-key"},
        )
        payload = await _first_sse_payload(response)

        receive.disconnect()
        await response.body_iterator.aclose()

        assert payload["event_id"] == "evt-acme-stream"

    @pytest.mark.asyncio
    async def test_stream_generator_stops_after_disconnect(self, client, monkeypatch):
        _prepare_stream_events(client)
        _disable_auth(client, monkeypatch)

        response, receive = await _dispatch_stream_request(client)
        await _first_sse_payload(response)

        receive.disconnect()

        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(response.body_iterator), timeout=2)

    def test_catalog_documents_streaming_source(self, client, monkeypatch):
        _disable_auth(client, monkeypatch)
        response = client.get("/v1/catalog")
        assert response.status_code == 200

        data = response.json()
        assert "streaming_sources" in data
        assert data["streaming_sources"]["events"]["path"] == "/v1/stream/events"
