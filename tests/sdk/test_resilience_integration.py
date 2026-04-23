from datetime import UTC, datetime

import httpx
import pytest
from agentflow.circuit_breaker import CircuitBreaker, CircuitOpenError
from agentflow.client import AgentFlowClient
from agentflow.retry import RetryPolicy


def _json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload)


def _health_payload() -> dict:
    return {
        "status": "healthy",
        "checked_at": datetime.now(UTC).isoformat(),
        "components": [],
    }


def test_configure_resilience_returns_self():
    client = AgentFlowClient("http://example.com", "test-key")

    result = client.configure_resilience(
        retry_policy=RetryPolicy(max_attempts=2, jitter_factor=0.0),
    )

    assert result is client
    assert client.retry_policy.max_attempts == 2


def test_default_resilience_is_applied():
    client = AgentFlowClient("http://example.com", "test-key")

    assert isinstance(client.retry_policy, RetryPolicy)
    assert isinstance(client.circuit_breaker, CircuitBreaker)


def test_circuit_open_blocks_request(monkeypatch):
    calls = {"count": 0}

    def _request(self, method, url, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _json_response(503, {"detail": "temporarily unavailable"})
        return _json_response(200, _health_payload())

    monkeypatch.setattr(httpx.Client, "request", _request)

    client = AgentFlowClient("http://example.com", "test-key").configure_resilience(
        retry_policy=RetryPolicy(max_attempts=1, jitter_factor=0.0),
        circuit_breaker=CircuitBreaker(failure_threshold=1, reset_timeout_s=999.0),
    )

    with pytest.raises(Exception):
        client.health()
    with pytest.raises(CircuitOpenError):
        client.health()

    assert calls["count"] == 1
