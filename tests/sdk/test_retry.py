import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow.client import AgentFlowClient
from agentflow.retry import RETRYABLE_STATUS, RetryPolicy, is_retryable_method


def test_client_source_has_no_signature_override():
    source = Path(inspect.getsourcefile(AgentFlowClient.__init__)).read_text(encoding="utf-8")

    assert "__signature__" not in source


def test_retry_policy_exponential_backoff():
    policy = RetryPolicy(max_attempts=5, initial_delay_s=0.1, jitter_factor=0.0)

    assert policy.compute_delay(0) == pytest.approx(0.1)
    assert policy.compute_delay(1) == pytest.approx(0.2)
    assert policy.compute_delay(2) == pytest.approx(0.4)
    assert policy.compute_delay(3) == pytest.approx(0.8)


def test_retry_policy_respects_retry_after_and_caps_at_max_delay():
    policy = RetryPolicy(initial_delay_s=0.1, max_delay_s=5.0, jitter_factor=0.0)

    assert policy.compute_delay(0, retry_after_s=3.0) == pytest.approx(3.0)
    assert policy.compute_delay(0, retry_after_s=999.0) == pytest.approx(5.0)


def test_retry_policy_jitter_stays_in_bounds():
    policy = RetryPolicy(initial_delay_s=1.0, jitter_factor=0.5)
    samples = [policy.compute_delay(0) for _ in range(100)]

    assert all(0.5 <= sample <= 1.5 for sample in samples)


def test_is_retryable_method_only_idempotent():
    assert is_retryable_method("GET") is True
    assert is_retryable_method("HEAD") is True
    assert is_retryable_method("PUT") is True
    assert is_retryable_method("DELETE") is True
    assert is_retryable_method("POST") is False


def test_retryable_statuses():
    assert 429 in RETRYABLE_STATUS
    assert 503 in RETRYABLE_STATUS
    assert 504 in RETRYABLE_STATUS
    assert 200 not in RETRYABLE_STATUS
    assert 404 not in RETRYABLE_STATUS
