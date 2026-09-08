"""The key-lookup pepper is refused in production when it is the public one (FB-07).

`key_lookup` is an HMAC of the API key itself, stored beside the argon2id hash
so `authenticate()` can find the candidate key in O(1) instead of scanning
every entry (M-C4). Its pepper decides whether that digest means anything
outside this deployment.

Until this gate, `compute_key_lookup` fell back to
`DEFAULT_KEY_LOOKUP_PEPPER` -- a constant committed to this repository -- and
nothing anywhere refused it. So a production install that never set the
variable stored digests anybody could recompute: hold a leaked
`api_keys.yaml`, guess a key, HMAC it with the published pepper, and a match
confirms the guess without ever paying for an argon2id verify. The same
constant also makes two deployments' digests joinable into one identity.

The query-analytics fingerprint pepper has had exactly this gate since AF-13,
which is what made the omission visible. This file pins the resolver, the hot
path that uses it, and the boot that must die before either can run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentflow_runtime.serving.api.main import app
from agentflow_runtime.serving.api.query_analytics_policy import (
    DEFAULT_FINGERPRINT_PEPPER,
    FINGERPRINT_PEPPER_ENV,
    QueryAnalyticsPolicyError,
)
from agentflow_runtime.serving.api.security import (
    DEFAULT_KEY_LOOKUP_PEPPER,
    KEY_LOOKUP_PEPPER_ENV,
    KeyLookupPepperError,
    compute_key_lookup,
    resolve_key_lookup_pepper,
)

OPERATOR_PEPPER = "an-operator-supplied-pepper-not-in-this-repository"


def _env(**overrides: str) -> dict[str, str]:
    return dict(overrides)


def test_dev_keeps_the_committed_default_so_a_fresh_checkout_starts() -> None:
    """The gate is production-only on purpose: `git clone && uvicorn` must not
    require an operator to invent a secret first."""
    assert resolve_key_lookup_pepper(_env()) == DEFAULT_KEY_LOOKUP_PEPPER
    assert resolve_key_lookup_pepper(_env(AGENTFLOW_PROFILE="dev")) == DEFAULT_KEY_LOOKUP_PEPPER
    assert resolve_key_lookup_pepper(_env(AGENTFLOW_DEMO_MODE="true")) == DEFAULT_KEY_LOOKUP_PEPPER


def test_production_refuses_an_unset_pepper() -> None:
    with pytest.raises(KeyLookupPepperError, match=KEY_LOOKUP_PEPPER_ENV):
        resolve_key_lookup_pepper(_env(AGENTFLOW_PROFILE="production"))


def test_production_refuses_the_committed_default() -> None:
    """Setting the variable to the value already printed in this file is not
    configuration; it is the same digest with an extra step."""
    with pytest.raises(KeyLookupPepperError, match="default pepper"):
        resolve_key_lookup_pepper(
            _env(
                AGENTFLOW_PROFILE="production",
                AGENTFLOW_KEY_LOOKUP_PEPPER=DEFAULT_KEY_LOOKUP_PEPPER,
            )
        )


def test_production_refuses_a_pepper_that_is_only_whitespace() -> None:
    """`AGENTFLOW_KEY_LOOKUP_PEPPER=" "` is a variable that looks set in
    `kubectl describe` and is not."""
    with pytest.raises(KeyLookupPepperError, match="to be set"):
        resolve_key_lookup_pepper(
            _env(AGENTFLOW_PROFILE="production", AGENTFLOW_KEY_LOOKUP_PEPPER="   ")
        )


def test_an_operator_pepper_is_returned_byte_for_byte() -> None:
    """Whitespace decides only whether the value counts as set. Trimming the
    returned value would change every digest a padded pepper had already
    produced -- silently sending an entire deployment back to the O(n) verify
    scan, which is the one thing adding a gate must not do."""
    padded = f"  {OPERATOR_PEPPER}  "
    resolved = resolve_key_lookup_pepper(
        _env(AGENTFLOW_PROFILE="production", AGENTFLOW_KEY_LOOKUP_PEPPER=padded)
    )

    assert resolved == padded


def test_compute_key_lookup_resolves_through_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal has to reach the caller that matters. `compute_key_lookup`
    is what issues a digest (key_rotation) and what matches one (manager), so a
    production process must not be able to compute one at all."""
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.delenv(KEY_LOOKUP_PEPPER_ENV, raising=False)

    with pytest.raises(KeyLookupPepperError):
        compute_key_lookup("some-api-key")

    monkeypatch.setenv(KEY_LOOKUP_PEPPER_ENV, OPERATOR_PEPPER)
    assert compute_key_lookup("some-api-key") == compute_key_lookup("some-api-key", OPERATOR_PEPPER)


def test_an_explicitly_passed_pepper_is_used_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller that hands over a pepper has already resolved it; re-checking
    the environment there would make the argument a lie."""
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.delenv(KEY_LOOKUP_PEPPER_ENV, raising=False)

    digest = compute_key_lookup("some-api-key", DEFAULT_KEY_LOOKUP_PEPPER)

    assert len(digest) == 64


def test_the_default_peppers_are_readable_in_this_repository() -> None:
    """The premise the whole gate rests on. Both defaults are source constants,
    so 'the pepper is secret' is false for anyone with the repository -- which
    for an open source project is everyone."""
    assert DEFAULT_KEY_LOOKUP_PEPPER
    assert DEFAULT_FINGERPRINT_PEPPER
    # Two digests over the same input must not collapse into one value just
    # because both peppers were left at their defaults.
    assert DEFAULT_KEY_LOOKUP_PEPPER != DEFAULT_FINGERPRINT_PEPPER


def test_a_production_boot_without_the_lookup_pepper_dies_in_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where the refusal belongs. Failing at boot means the operator sees it in
    a rollout that never becomes ready, not in a 500 on the first key check."""
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.setenv(FINGERPRINT_PEPPER_ENV, OPERATOR_PEPPER)
    monkeypatch.delenv(KEY_LOOKUP_PEPPER_ENV, raising=False)

    with pytest.raises(KeyLookupPepperError), TestClient(app):
        pass


def test_a_production_boot_without_the_fingerprint_pepper_dies_in_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AF-13's gate lived in `QueryAnalyticsPolicy.from_env`, which nothing
    called at boot -- so a production pod came up and only failed once a
    request reached the analytics path. Same refusal, moved to the same place
    as its sibling."""
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.setenv(KEY_LOOKUP_PEPPER_ENV, OPERATOR_PEPPER)
    monkeypatch.delenv(FINGERPRINT_PEPPER_ENV, raising=False)

    with pytest.raises(QueryAnalyticsPolicyError), TestClient(app):
        pass


def test_a_production_boot_with_both_peppers_comes_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.setenv(KEY_LOOKUP_PEPPER_ENV, OPERATOR_PEPPER)
    monkeypatch.setenv(FINGERPRINT_PEPPER_ENV, OPERATOR_PEPPER + "-fingerprint")

    with TestClient(app):
        assert app.state.profile == "production"
