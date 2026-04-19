import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

import agentflow.async_client as async_client_module
import agentflow.client as client_module
from agentflow import AsyncAgentFlowClient
from agentflow.client import AgentFlowClient
from agentflow.exceptions import AgentFlowError
from agentflow.retry import RetryPolicy


def _json_response(
    status_code: int,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload, headers=headers)


def _health_payload(status: str = "healthy") -> dict:
    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "components": [],
    }


def _install_sync_request_stub(monkeypatch, responses):
    calls = {"count": 0}

    def _request(self, method, url, **kwargs):
        index = calls["count"]
        calls["count"] += 1
        result = responses[index] if index < len(responses) else responses[-1]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.Client, "request", _request)
    return calls


def _install_async_request_stub(monkeypatch, responses):
    calls = {"count": 0}

    async def _request(self, method, url, **kwargs):
        index = calls["count"]
        calls["count"] += 1
        result = responses[index] if index < len(responses) else responses[-1]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.AsyncClient, "request", _request)
    return calls


def test_retry_policy_exponential_backoff():
    policy = RetryPolicy(max_attempts=5, initial_delay_s=0.1, jitter_factor=0.0)

    assert policy.compute_delay(0) == 0.1
    assert policy.compute_delay(1) == 0.2
    assert policy.compute_delay(2) == 0.4


def test_retry_policy_respects_retry_after():
    policy = RetryPolicy()

    assert policy.compute_delay(0, retry_after_s=3.0) == 3.0


def test_retry_policy_caps_at_max_delay():
    policy = RetryPolicy(max_delay_s=1.0, jitter_factor=0.0)

    assert policy.compute_delay(10) == 1.0


def test_client_retries_get_on_503(monkeypatch):
    calls = _install_sync_request_stub(
        monkeypatch,
        [
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(200, _health_payload()),
        ],
    )
    sleep_calls: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", sleep_calls.append)

    client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_s=0.01, jitter_factor=0.0),
    )

    health = client.health()

    assert health.status == "healthy"
    assert calls["count"] == 3
    assert sleep_calls == [0.01, 0.02]


def test_client_respects_retry_after_header(monkeypatch):
    calls = _install_sync_request_stub(
        monkeypatch,
        [
            _json_response(
                429,
                {"detail": "rate limit exceeded"},
                headers={"Retry-After": "2"},
            ),
            _json_response(200, _health_payload()),
        ],
    )
    sleep_calls: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", sleep_calls.append)

    client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=2, initial_delay_s=0.01, jitter_factor=0.0),
    )

    health = client.health()

    assert health.status == "healthy"
    assert calls["count"] == 2
    assert sleep_calls == [2.0]


def test_client_does_not_retry_post_by_default(monkeypatch):
    calls = _install_sync_request_stub(
        monkeypatch,
        [_json_response(503, {"detail": "temporarily unavailable"})],
    )
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)

    client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_s=0.01, jitter_factor=0.0),
    )

    with pytest.raises(AgentFlowError):
        client.batch([client.batch_entity("order", "ORD-1")])

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_async_client_retries_get_on_503(monkeypatch):
    calls = _install_async_request_stub(
        monkeypatch,
        [
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(200, _health_payload()),
        ],
    )
    sleep_calls: list[float] = []

    async def _sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(async_client_module.asyncio, "sleep", _sleep)

    client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_s=0.01, jitter_factor=0.0),
    )

    health = await client.health()

    assert health.status == "healthy"
    assert calls["count"] == 3
    assert sleep_calls == [0.01, 0.02]

    await client._http.aclose()


@pytest.mark.asyncio
async def test_async_client_does_not_retry_post_by_default(monkeypatch):
    calls = _install_async_request_stub(
        monkeypatch,
        [_json_response(503, {"detail": "temporarily unavailable"})],
    )

    async def _sleep(delay: float) -> None:
        raise AssertionError(f"unexpected sleep {delay}")

    monkeypatch.setattr(async_client_module.asyncio, "sleep", _sleep)

    client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=3, initial_delay_s=0.01, jitter_factor=0.0),
    )

    with pytest.raises(AgentFlowError):
        await client.batch([client.batch_entity("order", "ORD-1")])

    assert calls["count"] == 1

    await client._http.aclose()
