from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient

import src.serving.api.main as main_module
from src.processing.event_replayer import ensure_dead_letter_table
from src.serving.cache import QueryCache

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHAOS_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.chaos.yml"
TOXIPROXY_CONFIG_FILE = PROJECT_ROOT / "config" / "toxiproxy.json"
CHAOS_PROJECT_NAME = "agentflow-chaos"
CHAOS_API_KEY = "af-chaos-ops-key"
TOXIPROXY_API_PORT = int(os.getenv("AGENTFLOW_CHAOS_TOXIPROXY_PORT", "8474"))
TOXIPROXY_KAFKA_PORT = int(os.getenv("AGENTFLOW_CHAOS_KAFKA_PORT", "19092"))
TOXIPROXY_REDIS_PORT = int(os.getenv("AGENTFLOW_CHAOS_REDIS_PORT", "16380"))
CHAOS_SLO = {
    "tests/chaos/test_kafka_latency.py::test_replay_succeeds_through_kafka_latency_proxy": {
        "scenario": "kafka_latency_500ms",
        "expectation": "entity_lookup_still_200",
    },
    "tests/chaos/test_kafka_latency.py::test_replay_stays_pending_when_kafka_proxy_times_out": {
        "scenario": "kafka_down",
        "expectation": "replay_pending_and_metrics_still_200",
    },
    "tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled": {
        "scenario": "redis_down",
        "expectation": "requests_still_pass_200",
    },
    "tests/chaos/test_duckdb_timeout.py::test_metric_endpoint_returns_503_on_duckdb_timeout": {
        "scenario": "duckdb_timeout",
        "expectation": "returns_503_not_500",
    },
    "tests/chaos/test_duckdb_timeout.py::test_entity_endpoint_returns_503_on_duckdb_timeout": {
        "scenario": "duckdb_timeout",
        "expectation": "returns_503_not_500",
    },
}


def _is_ci_mode() -> bool:
    return os.getenv("AGENTFLOW_CHAOS_CI_MODE", "").lower() in {"1", "true", "yes", "on"}


def _startup_timeout() -> float:
    default_timeout = "120" if _is_ci_mode() else "60"
    return float(os.getenv("AGENTFLOW_CHAOS_STARTUP_TIMEOUT", default_timeout))


def _compose_command(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        CHAOS_PROJECT_NAME,
        "-f",
        str(CHAOS_COMPOSE_FILE),
        *args,
    ]


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {host}:{port}: {last_error}")


def _wait_for_toxiproxy_api(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/proxies", timeout=2.0)
            if response.status_code == 200:
                return
            last_error = f"unexpected status {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for Toxiproxy API: {last_error}")


def _wait_for_kafka(bootstrap_servers: str, timeout: float = 60.0) -> None:
    from confluent_kafka.admin import AdminClient

    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            admin = AdminClient(
                {
                    "bootstrap.servers": bootstrap_servers,
                    "socket.timeout.ms": 2000,
                }
            )
            admin.list_topics(timeout=2)
            return
        except Exception as exc:  # pragma: no cover - exercised in integration
            last_error = str(exc)
            time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for Kafka at {bootstrap_servers}: {last_error}")


def _wait_for_redis(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    client = AsyncRespRedisClient(host, port)
    while time.monotonic() < deadline:
        try:
            result = asyncio.run(client._command("PING"))
            if result == "PONG":
                return
            last_error = f"unexpected response {result!r}"
        except Exception as exc:  # pragma: no cover - exercised in integration
            last_error = str(exc)
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for Redis at {host}:{port}: {last_error}")


async def _clear_redis_query_cache(host: str, port: int) -> None:
    client = AsyncRespRedisClient(host, port)
    try:
        keys: list[str] = []
        for pattern in ("metric:*", "entity:*"):
            for key in await client.keys(pattern):
                keys.append(key.decode("utf-8") if isinstance(key, bytes) else str(key))
        if keys:
            await client.delete(*keys)
    finally:
        await client.aclose()


class AsyncRespRedisClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    async def get(self, key: str):
        return await self._command("GET", key)

    async def setex(self, key: str, ttl, value: str):
        seconds = int(ttl.total_seconds()) if hasattr(ttl, "total_seconds") else int(ttl)
        await self._command("SETEX", key, str(seconds), value)

    async def keys(self, pattern: str):
        return await self._command("KEYS", pattern)

    async def delete(self, *keys: str):
        if not keys:
            return 0
        return await self._command("DEL", *keys)

    async def aclose(self) -> None:
        return None

    async def _command(self, *parts: str):
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(self._encode(*parts))
            await writer.drain()
            return await self._read(reader)
        finally:
            writer.close()
            await writer.wait_closed()

    def _encode(self, *parts: str) -> bytes:
        chunks = [f"*{len(parts)}\r\n".encode()]
        for part in parts:
            encoded = part.encode("utf-8")
            chunks.append(f"${len(encoded)}\r\n".encode())
            chunks.append(encoded + b"\r\n")
        return b"".join(chunks)

    async def _read(self, reader: asyncio.StreamReader):
        prefix = await reader.readexactly(1)
        if prefix == b"+":
            return (await reader.readuntil(b"\r\n"))[:-2].decode("utf-8")
        if prefix == b":":
            return int((await reader.readuntil(b"\r\n"))[:-2])
        if prefix == b"$":
            length = int((await reader.readuntil(b"\r\n"))[:-2])
            if length == -1:
                return None
            data = await reader.readexactly(length)
            await reader.readexactly(2)
            return data
        if prefix == b"*":
            length = int((await reader.readuntil(b"\r\n"))[:-2])
            if length == -1:
                return None
            return [await self._read(reader) for _ in range(length)]
        if prefix == b"-":
            error = (await reader.readuntil(b"\r\n"))[:-2].decode("utf-8")
            raise RuntimeError(error)
        raise RuntimeError(f"Unsupported Redis response prefix: {prefix!r}")


@dataclass
class ChaosContext:
    client: TestClient
    db_path: Path


class ToxiproxyClient:
    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=10.0)

    def close(self) -> None:
        self._client.close()

    def reset(self) -> None:
        response = self._client.post("/reset")
        response.raise_for_status()

    def populate(self, proxies: list[dict[str, Any]]) -> None:
        response = self._client.post("/populate", json=proxies)
        response.raise_for_status()

    def add_toxic(
        self,
        proxy_name: str,
        toxic_name: str,
        toxic_type: str,
        attributes: dict[str, Any],
        *,
        stream: str = "downstream",
        toxicity: float = 1.0,
    ) -> None:
        response = self._client.post(
            f"/proxies/{proxy_name}/toxics",
            json={
                "name": toxic_name,
                "type": toxic_type,
                "stream": stream,
                "toxicity": toxicity,
                "attributes": attributes,
            },
        )
        response.raise_for_status()

    def remove_toxic(self, proxy_name: str, toxic_name: str) -> None:
        response = self._client.delete(f"/proxies/{proxy_name}/toxics/{toxic_name}")
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()

    def delete_proxy(self, proxy_name: str) -> None:
        response = self._client.delete(f"/proxies/{proxy_name}")
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()

    def enable_proxy(self, proxy_name: str) -> None:
        self._set_proxy_enabled(proxy_name, True)

    def disable_proxy(self, proxy_name: str) -> None:
        self._set_proxy_enabled(proxy_name, False)

    def _set_proxy_enabled(self, proxy_name: str, enabled: bool) -> None:
        response = self._client.post(
            f"/proxies/{proxy_name}",
            json={"enabled": enabled},
        )
        response.raise_for_status()


@pytest.fixture(scope="session")
def chaos_stack():
    if os.getenv("SKIP_DOCKER_TESTS") == "1":
        pytest.skip("SKIP_DOCKER_TESTS=1")
    startup_timeout = _startup_timeout()
    if not _is_ci_mode():
        subprocess.run(
            _compose_command(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                str(int(startup_timeout)),
                "--remove-orphans",
            ),
            cwd=PROJECT_ROOT,
            check=True,
        )
    _wait_for_port("127.0.0.1", TOXIPROXY_API_PORT, timeout=startup_timeout)
    _wait_for_port("127.0.0.1", TOXIPROXY_KAFKA_PORT, timeout=startup_timeout)
    _wait_for_port("127.0.0.1", TOXIPROXY_REDIS_PORT, timeout=startup_timeout)
    _wait_for_toxiproxy_api(f"http://127.0.0.1:{TOXIPROXY_API_PORT}", timeout=startup_timeout)
    _wait_for_kafka(f"127.0.0.1:{TOXIPROXY_KAFKA_PORT}", timeout=startup_timeout)
    _wait_for_redis("127.0.0.1", TOXIPROXY_REDIS_PORT, timeout=startup_timeout)
    yield {
        "toxiproxy_url": f"http://127.0.0.1:{TOXIPROXY_API_PORT}",
        "kafka_bootstrap": f"127.0.0.1:{TOXIPROXY_KAFKA_PORT}",
        "redis_host": "127.0.0.1",
        "redis_port": TOXIPROXY_REDIS_PORT,
    }
    if not _is_ci_mode():
        subprocess.run(
            _compose_command("down", "-v"),
            cwd=PROJECT_ROOT,
            check=True,
        )


@pytest.fixture
def toxiproxy_client(chaos_stack):
    client = ToxiproxyClient(chaos_stack["toxiproxy_url"])
    proxies = json.loads(TOXIPROXY_CONFIG_FILE.read_text(encoding="utf-8"))
    client.populate(proxies)
    client.reset()
    try:
        yield client
    finally:
        client.reset()
        client.close()


@pytest.fixture(autouse=True)
def reset_redis_query_cache_between_chaos_tests(request: pytest.FixtureRequest):
    if "chaos_stack" not in request.fixturenames:
        yield
        return
    chaos_stack = request.getfixturevalue("chaos_stack")
    toxiproxy_client = request.getfixturevalue("toxiproxy_client")

    toxiproxy_client.enable_proxy("redis")
    asyncio.run(
        _clear_redis_query_cache(chaos_stack["redis_host"], chaos_stack["redis_port"])
    )
    try:
        yield
    finally:
        toxiproxy_client.enable_proxy("redis")
        asyncio.run(
            _clear_redis_query_cache(chaos_stack["redis_host"], chaos_stack["redis_port"])
        )


@pytest.fixture
def chaos_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChaosContext:
    db_path = tmp_path / "chaos.duckdb"
    usage_db_path = tmp_path / "chaos_usage.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(usage_db_path))
    monkeypatch.setenv("AGENTFLOW_API_KEYS", f"{CHAOS_API_KEY}:Chaos Ops")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    main_module.app.state.webhook_dispatcher_autostart = False
    main_module.app.state.alert_dispatcher_autostart = False
    with TestClient(main_module.app) as client:
        yield ChaosContext(client=client, db_path=db_path)


@pytest.fixture
def chaos_client(chaos_context: ChaosContext) -> TestClient:
    return chaos_context.client


@pytest.fixture
def chaos_headers() -> dict[str, str]:
    return {"X-API-Key": CHAOS_API_KEY}


@pytest.hookimpl(optionalhook=True)
def pytest_json_runtest_metadata(item: pytest.Item, call) -> dict[str, Any]:
    del call
    metadata = CHAOS_SLO.get(item.nodeid, {})
    return {
        "ci_mode": _is_ci_mode(),
        **metadata,
    }


def install_redis_query_cache(chaos_client: TestClient, chaos_stack) -> QueryCache:
    cache = QueryCache(
        redis_client=AsyncRespRedisClient(
            host=chaos_stack["redis_host"],
            port=chaos_stack["redis_port"],
        )
    )
    chaos_client.app.state.query_cache = cache
    return cache


def install_deadletter_producer(
    chaos_client: TestClient,
    bootstrap_servers: str,
    *,
    socket_timeout_ms: int = 2000,
    message_timeout_ms: int = 2000,
    flush_timeout_seconds: int = 5,
) -> None:
    from confluent_kafka import Producer

    def produce(topic: str, payload: dict) -> None:
        delivery_errors: list[str] = []

        def on_delivery(err, msg) -> None:
            del msg
            if err is not None:
                delivery_errors.append(str(err))

        producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "socket.timeout.ms": socket_timeout_ms,
                "message.timeout.ms": message_timeout_ms,
            }
        )
        producer.produce(
            topic,
            key=str(payload.get("event_id", "")),
            value=json.dumps(payload).encode("utf-8"),
            on_delivery=on_delivery,
        )
        remaining = producer.flush(flush_timeout_seconds)
        if delivery_errors:
            raise RuntimeError(delivery_errors[0])
        if remaining != 0:
            raise RuntimeError(f"{remaining} Kafka message(s) were not delivered")

    chaos_client.app.state.deadletter_producer = produce


def seed_deadletter_event(db_path: Path, event_id: str) -> dict[str, Any]:
    payload = {
        "event_id": event_id,
        "event_type": "order.created",
        "timestamp": "2026-04-11T12:00:00+00:00",
        "source": "chaos-test",
        "order_id": "ORD-20260411-9001",
        "user_id": "USR-42",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 1, "unit_price": "79.99"},
            {"product_id": "PROD-002", "quantity": 1, "unit_price": "20.00"},
        ],
        "total_amount": "99.99",
        "currency": "USD",
    }
    conn = duckdb.connect(str(db_path))
    try:
        ensure_dead_letter_table(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO dead_letter_events (
                event_id,
                event_type,
                payload,
                failure_reason,
                failure_detail,
                received_at,
                retry_count,
                last_retried_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL, 'failed')
            """,
            [
                event_id,
                payload["event_type"],
                json.dumps(payload),
                "semantic_validation",
                "chaos replay",
            ],
        )
    finally:
        conn.close()
    return payload


def deadletter_status(db_path: Path, event_id: str) -> tuple[str, int] | None:
    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT status, retry_count FROM dead_letter_events WHERE event_id = ?",
            [event_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row[0]), int(row[1] or 0)


def outbox_status(db_path: Path, event_id: str) -> tuple[str, int, str | None] | None:
    conn = duckdb.connect(str(db_path))
    try:
        row = conn.execute(
            """
            SELECT status, retry_count, last_error
            FROM outbox
            WHERE event_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [event_id],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row[0]), int(row[1] or 0), row[2]
