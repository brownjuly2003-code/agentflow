import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

import agentflow.circuit_breaker as circuit_breaker_module
from agentflow import AsyncAgentFlowClient
from agentflow.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from agentflow.client import AgentFlowClient
from agentflow.exceptions import AgentFlowError
from agentflow.retry import RetryPolicy


def _json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def _health_payload() -> dict:
    return {
        "status": "healthy",
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


def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_breaker_resets_after_timeout(monkeypatch):
    current = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: current[0])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)

    breaker.record_failure()
    current[0] += 0.15
    breaker.before_call()

    assert breaker.state == CircuitState.HALF_OPEN


def test_breaker_half_open_success_closes(monkeypatch):
    current = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: current[0])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)

    breaker.record_failure()
    current[0] += 0.15
    breaker.before_call()
    breaker.record_success()

    assert breaker.state == CircuitState.CLOSED


def test_breaker_half_open_failure_reopens(monkeypatch):
    current = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: current[0])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.1)

    breaker.record_failure()
    current[0] += 0.15
    breaker.before_call()
    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN


def test_breaker_allows_one_probe_in_half_open(monkeypatch):
    current = [100.0]
    monkeypatch.setattr(circuit_breaker_module.time, "monotonic", lambda: current[0])
    breaker = CircuitBreaker(
        failure_threshold=1,
        reset_timeout_s=0.1,
        half_open_max_calls=1,
    )

    breaker.record_failure()
    current[0] += 0.15
    breaker.before_call()

    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_client_breaker_opens_after_repeated_failures(monkeypatch):
    calls = _install_sync_request_stub(
        monkeypatch,
        [
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(200, _health_payload()),
        ],
    )
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=30.0)
    client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, initial_delay_s=0.01, jitter_factor=0.0),
        circuit_breaker=breaker,
    )

    with pytest.raises(AgentFlowError):
        client.health()
    with pytest.raises(AgentFlowError):
        client.health()
    with pytest.raises(CircuitOpenError):
        client.health()

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_async_client_breaker_opens_after_failure(monkeypatch):
    calls = _install_async_request_stub(
        monkeypatch,
        [
            _json_response(503, {"detail": "temporarily unavailable"}),
            _json_response(200, _health_payload()),
        ],
    )
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=30.0)
    client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, initial_delay_s=0.01, jitter_factor=0.0),
        circuit_breaker=breaker,
    )

    with pytest.raises(AgentFlowError):
        await client.health()
    with pytest.raises(CircuitOpenError):
        await client.health()

    assert calls["count"] == 1

    await client._http.aclose()
