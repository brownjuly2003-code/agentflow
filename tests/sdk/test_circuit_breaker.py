import inspect
from pathlib import Path

import agentflow.circuit_breaker as circuit_breaker_module
import pytest
from agentflow import AsyncAgentFlowClient
from agentflow.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_async_client_source_has_no_signature_override():
    source = Path(inspect.getsourcefile(AsyncAgentFlowClient.__init__)).read_text(encoding="utf-8")

    assert "__signature__" not in source


def test_breaker_starts_closed():
    breaker = CircuitBreaker()

    assert breaker.state == CircuitState.CLOSED
    breaker.before_call()


def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_breaker_resets_to_half_open_after_timeout(monkeypatch):
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


def test_breaker_half_open_allows_one_probe(monkeypatch):
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


def test_breaker_success_resets_failure_counter():
    breaker = CircuitBreaker(failure_threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == CircuitState.CLOSED
