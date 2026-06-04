"""Unit tests for the progressive-kwarg-fallback helpers in agent_query.

The agent endpoints call query-engine methods whose signatures vary across
implementations (older engines and many test fakes predate ``tenant_id`` /
``allowed_tables``). Before F-4 the routers carried three hand-rolled nested
``try/except TypeError`` cascades with identical semantics; these tests pin
that exact behaviour onto the shared helpers that replaced them:

- kwargs are dropped progressively: full set → without ``allowed_tables`` →
  without ``tenant_id`` → bare call;
- a ``TypeError`` only triggers the next attempt when its message mentions a
  kwarg of the CURRENT attempt — anything else re-raises immediately (a
  genuine ``TypeError`` from inside the engine must not be swallowed).
"""

from __future__ import annotations

import pytest

from src.serving.api.routers.agent_query import (
    _call_in_threadpool_with_kwarg_fallback,
    _call_with_kwarg_fallback,
    _kwarg_fallback_attempts,
)


def test_attempts_drop_allowed_tables_then_tenant_id():
    attempts = _kwarg_fallback_attempts({"tenant_id": "acme", "allowed_tables": ["orders_v2"]})

    assert attempts == [
        {"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
        {"tenant_id": "acme"},
        {},
    ]


def test_attempts_for_tenant_only_drop_to_bare_call():
    attempts = _kwarg_fallback_attempts({"tenant_id": "acme"})

    assert attempts == [{"tenant_id": "acme"}, {}]


def test_modern_signature_gets_all_kwargs_first_try():
    seen: dict = {}

    def engine_method(question, *, limit, tenant_id=None, allowed_tables=None):
        seen.update(
            question=question, limit=limit, tenant_id=tenant_id, allowed_tables=allowed_tables
        )
        return "ok"

    result = _call_with_kwarg_fallback(
        engine_method,
        "top products",
        optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
        limit=5,
    )

    assert result == "ok"
    assert seen == {
        "question": "top products",
        "limit": 5,
        "tenant_id": "acme",
        "allowed_tables": ["orders_v2"],
    }


def test_legacy_signature_without_allowed_tables_falls_back_once():
    calls: list[dict] = []

    def engine_method(question, *, tenant_id=None):
        calls.append({"tenant_id": tenant_id})
        return "ok"

    result = _call_with_kwarg_fallback(
        engine_method,
        "q",
        optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
    )

    assert result == "ok"
    # First attempt raised on allowed_tables, second succeeded with tenant_id.
    assert calls == [{"tenant_id": "acme"}]


def test_oldest_signature_falls_back_to_bare_call():
    calls: list[str] = []

    def engine_method(question):
        calls.append(question)
        return "ok"

    result = _call_with_kwarg_fallback(
        engine_method,
        "q",
        optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
    )

    assert result == "ok"
    assert calls == ["q"]


def test_unrelated_typeerror_is_not_swallowed():
    def engine_method(question, *, tenant_id=None, allowed_tables=None):
        raise TypeError("cannot concatenate str and int")

    with pytest.raises(TypeError, match="concatenate"):
        _call_with_kwarg_fallback(
            engine_method,
            "q",
            optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
        )


def test_internal_typeerror_mentioning_kwarg_on_bare_attempt_reraises():
    # Once every optional kwarg is dropped there is nothing left to retry:
    # even a message that happens to contain "tenant_id" must propagate.
    def engine_method(question):
        raise TypeError("internal: tenant_id lookup blew up")

    with pytest.raises(TypeError, match="blew up"):
        _call_with_kwarg_fallback(
            engine_method,
            "q",
            optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
        )


async def test_threadpool_variant_preserves_fallback_semantics():
    calls: list[dict] = []

    def engine_method(question, *, tenant_id=None):
        calls.append({"question": question, "tenant_id": tenant_id})
        return {"rows": []}

    result = await _call_in_threadpool_with_kwarg_fallback(
        engine_method,
        "q",
        optional_kwargs={"tenant_id": "acme", "allowed_tables": ["orders_v2"]},
    )

    assert result == {"rows": []}
    assert calls == [{"question": "q", "tenant_id": "acme"}]
