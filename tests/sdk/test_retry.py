import inspect
from pathlib import Path

import pytest
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
    assert is_retryable_method("OPTIONS") is True
    assert is_retryable_method("POST") is False


def test_is_retryable_method_normalizes_the_verb():
    # Both SDK clients hand this whatever the caller wrote.
    assert is_retryable_method("get") is True
    assert is_retryable_method("post") is False


# --------------------------------------------------------------------------- #
# POST with an Idempotency-Key. This branch decides whether a write is replayed
# after a 429/502/503/504, so getting it wrong duplicates the write — and it had
# no tests at all, which is why retry.py sat at exactly its 75% mutation
# threshold (run 34265359911: 5 survivors, all in is_retryable_method).
# --------------------------------------------------------------------------- #


def test_post_is_retryable_when_a_mapping_carries_an_idempotency_key():
    assert is_retryable_method("POST", headers={"Idempotency-Key": "abc"}) is True


def test_post_idempotency_key_is_matched_case_insensitively():
    # HTTP header names are case-insensitive and every client spells this one
    # differently; a case-sensitive match would silently stop retrying.
    assert is_retryable_method("POST", headers={"IDEMPOTENCY-KEY": "abc"}) is True
    assert is_retryable_method("POST", headers={"idempotency-key": "abc"}) is True


def test_post_idempotency_key_is_found_among_other_headers():
    # One matching header is enough — the check is `any`, not `all`.
    headers = {"Content-Type": "application/json", "Idempotency-Key": "abc"}
    assert is_retryable_method("POST", headers=headers) is True


def test_post_is_not_retryable_on_a_merely_similar_header():
    assert is_retryable_method("POST", headers={"Idempotency": "abc"}) is False
    assert is_retryable_method("POST", headers={"X-Request-Id": "abc"}) is False


def test_post_is_not_retryable_without_usable_headers():
    assert is_retryable_method("POST", headers=None) is False
    assert is_retryable_method("POST", headers={}) is False


def test_post_accepts_the_idempotency_key_from_a_header_sequence():
    # httpx hands headers over as pairs, not a mapping.
    headers = [("Content-Type", "application/json"), ("Idempotency-Key", "abc")]
    assert is_retryable_method("POST", headers=headers) is True


def test_header_sequence_matches_on_the_name_not_the_value():
    # A pair whose *value* is the key name must not count.
    assert is_retryable_method("POST", headers=[("X-Header", "Idempotency-Key")]) is False
    assert is_retryable_method("POST", headers=[("Content-Type", "application/json")]) is False


def test_a_non_idempotent_verb_other_than_post_ignores_the_key():
    # The header rescues POST only; PATCH is not made safe by announcing one.
    assert is_retryable_method("PATCH", headers={"Idempotency-Key": "abc"}) is False


def test_retryable_statuses():
    assert 429 in RETRYABLE_STATUS
    assert 503 in RETRYABLE_STATUS
    assert 504 in RETRYABLE_STATUS
    assert 200 not in RETRYABLE_STATUS
    assert 404 not in RETRYABLE_STATUS
