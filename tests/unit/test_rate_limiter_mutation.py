"""Narrow, duckdb-free mutation test for the API rate limiter
(src/serving/api/rate_limiter.py).

This is the test the mutation gate runs against ``serving/api/rate_limiter.py``
(see scripts/mutation_report.py MODULE_TARGETS). The rate limiter is the API
abuse-protection hot path: a surviving mutant in its sliding-window arithmetic or
its fail-closed Redis fallback is a real DoS / brute-force exposure
(audit_28_06_26.md #7), exactly the kind of code a mutation gate should pin.

Three design rules, the first two shared with test_sql_guard_mutation.py (see
the sql_guard entries in fable_handoff.md cont.16-17):

1. **duckdb-free.** The ordinary tests/unit/test_rate_limiter.py builds the auth
   middleware -> AuthManager -> a DuckDB usage table, which drags duckdb's
   compiled subpackage into mutmut's ``mutants/`` workspace and crashes the run.
   This file touches only ``RateLimiter`` and in-process fakes (no Redis, no
   DuckDB), so mutmut can mutate the module cleanly.

2. **No fixtures -- inline construction + direct method calls.** With
   ``mutate_only_covered_lines = true`` the gate collects coverage first; a
   fixture-built limiter left every method line uncovered, so only ``__init__``
   got mutated (score 0%). Building the limiter inline and calling
   ``check()`` / ``_check_local()`` directly attributes every method line so the
   whole module is mutated.

3. **src.constants shim.** rate_limiter does
   ``from src.constants import DEFAULT_RATE_LIMIT_WINDOW_SECONDS``, but the
   mutation harness copies ``src/serving`` to a top-level ``serving`` package
   *without* ``src`` (copying ``src`` would shadow that ``serving`` with
   ``src.serving``). We register a stub ``src.constants`` (the real default, 60)
   before importing the module so the import resolves. The value is not an
   unbacked claim: the dual-context import below pulls the REAL ``src.constants``
   under ordinary pytest, where ``test_real_default_window_is_sixty_seconds``
   asserts the 60 s default -- so a production change to the constant fails the
   ordinary suite instead of silently passing here.

Dual-context import: under the mutation harness the module is copied to the
workspace as a top-level ``serving`` package (no ``src.`` prefix, which mutmut's
trampoline rejects); under ordinary pytest it lives under the ``src`` package.
"""

from __future__ import annotations

import asyncio
import sys
import types

try:  # ordinary pytest: the real src package is importable
    import src.constants  # noqa: F401
except ModuleNotFoundError:  # mutation harness: synthesize the one constant
    _src = sys.modules.setdefault("src", types.ModuleType("src"))
    _constants = types.ModuleType("src.constants")
    _constants.DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
    _src.constants = _constants
    sys.modules["src.constants"] = _constants

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.api import rate_limiter as rate_limiter_module
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.api import rate_limiter as rate_limiter_module

RateLimiter = rate_limiter_module.RateLimiter


# --------------------------------------------------------------------------- #
# In-process fakes (no Redis, no DuckDB).
# --------------------------------------------------------------------------- #


class _RecordingPipeline:
    """Records each pipeline command so the call arguments (expiry multiplier,
    zremrangebyscore window, zrange bounds, ...) can be pinned, and returns the
    parent's scripted ``results`` list from execute()."""

    def __init__(self, parent: _ScriptedRedis) -> None:
        self._parent = parent
        self.calls: list[tuple] = []

    def zremrangebyscore(self, key, minimum, maximum):
        self.calls.append(("zremrangebyscore", (key, minimum, maximum)))
        return self

    def zadd(self, key, mapping):
        self.calls.append(("zadd", (key, mapping)))
        return self

    def zcard(self, key):
        self.calls.append(("zcard", (key,)))
        return self

    def expire(self, key, ttl):
        self.calls.append(("expire", (key, ttl)))
        return self

    def zrange(self, key, start, stop, withscores=False):
        self.calls.append(("zrange", (key, start, stop), {"withscores": withscores}))
        return self

    async def execute(self):
        if self._parent.raise_on_execute is not None:
            raise self._parent.raise_on_execute
        return self._parent.results


class _ScriptedRedis:
    """Redis double whose pipeline returns a fixed ``results`` list, so each
    ``results[i]`` index mutant and each arithmetic mutant in the redis branch is
    pinnable. ``results`` is [zrem, zadd, zcard(count), expire, zrange(oldest)]."""

    def __init__(self, results=None, raise_on_execute=None) -> None:
        self.results = results if results is not None else [0, 1, 0, True, []]
        self.raise_on_execute = raise_on_execute
        self.pipelines: list[_RecordingPipeline] = []

    def pipeline(self):
        pipe = _RecordingPipeline(self)
        self.pipelines.append(pipe)
        return pipe


class _FakeRedisModule:
    """Stand-in for the module-level ``redis`` so __init__'s
    ``redis.from_url(redis_url)`` line is exercised without a live server."""

    def __init__(self, client) -> None:
        self._client = client
        self.from_url_calls: list[str] = []

    def from_url(self, url):
        self.from_url_calls.append(url)
        return self._client


class _LoggerSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict]] = []

    def warning(self, event, **kwargs):
        self.warning_calls.append((event, kwargs))


_SENTINEL = object()


def _local_limiter(time_source=lambda: 1_000.0):
    """A limiter whose _redis is a non-None sentinel, so __init__ skips from_url
    and check() takes the redis branch only if we hand it a real fake. For the
    pure _check_local() tests we call the method directly with an explicit now."""
    return RateLimiter(redis_client=_SENTINEL, time_source=time_source)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# src.constants: pin the real default so the harness stub can't drift unnoticed.
# --------------------------------------------------------------------------- #


def test_real_default_window_is_sixty_seconds():
    # Under ordinary pytest this imports the REAL constant; if production changes
    # it, this fails here -- the harness stub (60) would otherwise pass silently.
    assert rate_limiter_module.DEFAULT_RATE_LIMIT_WINDOW_SECONDS == 60


# --------------------------------------------------------------------------- #
# Module constant.
# --------------------------------------------------------------------------- #


def test_redis_window_expiry_multiplier_is_two():
    assert rate_limiter_module.REDIS_WINDOW_EXPIRY_MULTIPLIER == 2


# --------------------------------------------------------------------------- #
# __init__: redis client wiring (pins the `is None and ... is not None` guard,
# from_url, and the default redis_url).
# --------------------------------------------------------------------------- #


def test_init_keeps_explicit_client_and_does_not_call_from_url(monkeypatch):
    # _redis is not None -> `self._redis is None` is False -> guard short-circuits
    # and from_url is never called. Kills `and`->`or` and the first `is`->`is not`
    # (either flip would overwrite the explicit client via from_url).
    fake_module = _FakeRedisModule(client="from-url-client")
    monkeypatch.setattr(rate_limiter_module, "redis", fake_module)
    limiter = RateLimiter(redis_client=_SENTINEL)
    assert limiter._redis is _SENTINEL
    assert fake_module.from_url_calls == []


def test_init_builds_client_from_url_when_none_and_redis_available(monkeypatch):
    # redis_client is None and module redis is present -> from_url is called with
    # the default url. Kills the second `is not`->`is` flip (which would skip
    # from_url and leave _redis None) and the default redis_url string mutant.
    fake_module = _FakeRedisModule(client="built-client")
    monkeypatch.setattr(rate_limiter_module, "redis", fake_module)
    limiter = RateLimiter(redis_client=None)
    assert limiter._redis == "built-client"
    assert fake_module.from_url_calls == ["redis://localhost:6379"]


def test_init_honors_custom_redis_url(monkeypatch):
    fake_module = _FakeRedisModule(client="built-client")
    monkeypatch.setattr(rate_limiter_module, "redis", fake_module)
    RateLimiter(redis_client=None, redis_url="redis://example:6380")
    assert fake_module.from_url_calls == ["redis://example:6380"]


def test_init_no_client_when_redis_unavailable(monkeypatch):
    # redis_client is None and module redis is None -> _redis stays None.
    monkeypatch.setattr(rate_limiter_module, "redis", None)
    limiter = RateLimiter(redis_client=None)
    assert limiter._redis is None


# --------------------------------------------------------------------------- #
# _check_local: the sliding-window arithmetic (the fail-closed core).
# --------------------------------------------------------------------------- #


def test_check_local_first_request_allowed_with_full_remaining():
    limiter = _local_limiter()
    allowed, remaining, reset_at = limiter._check_local("k", 2, 60, 1_000.0)
    assert allowed is True
    assert remaining == 1  # max(0, 2 - 1)
    assert reset_at == 1_060  # int(window[0] + window_seconds) = int(1000 + 60)


def test_check_local_second_request_allowed_with_zero_remaining():
    limiter = _local_limiter()
    limiter._check_local("k", 2, 60, 1_000.0)
    allowed, remaining, reset_at = limiter._check_local("k", 2, 60, 1_000.0)
    assert allowed is True
    assert remaining == 0  # max(0, 2 - 2); kills `0`->`1` in the max guard
    assert reset_at == 1_060


def test_check_local_blocks_when_window_count_equals_limit():
    # len(window) == limit must block: pins `>=`->`>` on the limit check.
    limiter = _local_limiter()
    limiter._check_local("k", 2, 60, 1_000.0)
    limiter._check_local("k", 2, 60, 1_000.0)
    allowed, remaining, reset_at = limiter._check_local("k", 2, 60, 1_000.0)
    assert allowed is False
    assert remaining == 0
    assert reset_at == 1_060  # int(window[0] + window_seconds), window[0] == 1000


def test_check_local_zero_limit_blocks_via_empty_window_branch():
    # limit == 0 with a fresh (empty) window: len([]) >= 0 is True and the window
    # is empty, so reset_at takes the `else int(now + window_seconds)` branch.
    limiter = _local_limiter()
    allowed, remaining, reset_at = limiter._check_local("k", 0, 60, 1_000.0)
    assert allowed is False
    assert remaining == 0
    assert reset_at == 1_060  # int(now + window_seconds); kills the else `+`->`-`


def test_check_local_blocked_reset_uses_oldest_stamp_not_now():
    # A non-empty blocked window resets off window[0], not now. Pins the ternary's
    # true branch (`int(window[0] + window_seconds)`) and window[0] indexing.
    limiter = _local_limiter()
    limiter._windows["k"] = [950.0]
    allowed, _, reset_at = limiter._check_local("k", 1, 60, 1_000.0)
    assert allowed is False
    assert reset_at == 1_010  # int(950 + 60), NOT int(1000 + 60)


def test_check_local_cutoff_retains_stamp_just_inside_window():
    # cutoff = now - window_seconds. A stamp newer than cutoff is retained, so it
    # counts toward the limit. Kills cutoff `-`->`+` (which would push cutoff into
    # the future and drop every stamp).
    limiter = _local_limiter()
    limiter._windows["k"] = [950.0]  # 950 > (1000 - 60 = 940) -> retained
    allowed, _, _ = limiter._check_local("k", 1, 60, 1_000.0)
    assert allowed is False  # retained stamp fills the limit of 1


def test_check_local_prune_is_strictly_greater_than_cutoff():
    # The comprehension keeps `stamp > cutoff`, not `>=`: a stamp exactly at the
    # cutoff is dropped. Kills `>`->`>=`.
    limiter = _local_limiter()
    limiter._windows["k"] = [940.0]  # 940 == cutoff (1000 - 60) -> dropped
    allowed, remaining, _ = limiter._check_local("k", 1, 60, 1_000.0)
    assert allowed is True  # the boundary stamp was pruned, leaving room
    assert remaining == 0


def test_check_local_expires_old_stamps_across_calls():
    # An old stamp outside the window is pruned and persisted (self._windows[key]
    # = window), so a later call sees a clean window.
    limiter = _local_limiter()
    limiter._windows["k"] = [100.0, 200.0]  # both far older than 1000 - 60
    allowed, remaining, reset_at = limiter._check_local("k", 2, 60, 1_000.0)
    assert allowed is True
    assert remaining == 1
    assert limiter._windows["k"] == [1_000.0]  # pruned old + appended now


def test_check_local_is_isolated_per_key():
    limiter = _local_limiter()
    limiter._check_local("a", 1, 60, 1_000.0)
    blocked, _, _ = limiter._check_local("a", 1, 60, 1_000.0)
    other_allowed, other_remaining, _ = limiter._check_local("b", 1, 60, 1_000.0)
    assert blocked is False
    assert other_allowed is True
    assert other_remaining == 0


# --------------------------------------------------------------------------- #
# check(): local branch (self._redis is None).
# --------------------------------------------------------------------------- #


def test_check_routes_to_local_when_redis_is_none(monkeypatch):
    # self._redis is None -> check() returns _check_local(...). Pins the
    # `if self._redis is None` branch and the local default window.
    monkeypatch.setattr(rate_limiter_module, "redis", None)
    limiter = RateLimiter(redis_client=None, time_source=lambda: 1_000.0)
    allowed, remaining, reset_at = _run(limiter.check("k", 2))
    assert allowed is True
    assert remaining == 1
    assert reset_at == 1_060


def test_check_local_branch_uses_default_window(monkeypatch):
    # check() called without window_seconds uses DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    # (60). Pins the default-arg line; a `->None` mutant would raise on int(+None).
    monkeypatch.setattr(rate_limiter_module, "redis", None)
    limiter = RateLimiter(redis_client=None, time_source=lambda: 1_000.0)
    _, _, reset_at = _run(limiter.check("k", 5))
    assert reset_at == 1_060  # 1000 + 60


def test_check_local_branch_blocks_over_limit(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "redis", None)
    limiter = RateLimiter(redis_client=None, time_source=lambda: 1_000.0)
    _run(limiter.check("k", 2))
    _run(limiter.check("k", 2))
    allowed, remaining, _ = _run(limiter.check("k", 2))
    assert allowed is False
    assert remaining == 0


def test_check_local_branch_is_isolated_per_key(monkeypatch):
    # The local branch must forward the real key to _check_local: a mutant that
    # drops it (-> None) would collapse every caller onto one shared window.
    monkeypatch.setattr(rate_limiter_module, "redis", None)
    limiter = RateLimiter(redis_client=None, time_source=lambda: 1_000.0)
    _run(limiter.check("a", 1))
    a_blocked, _, _ = _run(limiter.check("a", 1))
    b_allowed, b_remaining, _ = _run(limiter.check("b", 1))
    assert a_blocked is False
    assert b_allowed is True  # "b" is not throttled by "a"'s count
    assert b_remaining == 0


# --------------------------------------------------------------------------- #
# check(): redis branch (happy path) -- pins the pipeline commands and the
# count / oldest-entry / reset arithmetic.
# --------------------------------------------------------------------------- #


def _redis_limiter(results=None, time_source=lambda: 1_000.0):
    redis_double = _ScriptedRedis(results=results)
    limiter = RateLimiter(redis_client=redis_double, time_source=time_source)
    return limiter, redis_double


def test_check_redis_allows_when_count_below_limit():
    # results[2] (zcard) == 3 count; oldest entry sets reset off its score.
    limiter, redis_double = _redis_limiter(results=[0, 1, 3, True, [("member", 950.0)]])
    allowed, remaining, reset_at = _run(limiter.check("k", 5, 60))
    assert allowed is True  # count 3 <= limit 5
    assert remaining == 2  # max(0, 5 - 3)
    assert reset_at == 1_010  # int(float(950.0) + 60), from the oldest entry


def test_check_redis_count_comes_from_index_two_not_three():
    # results[2] is the zcard count; results[3] is the expire result. Pins the
    # `results[2]` index: reading results[3] (True -> 1) would change remaining.
    limiter, _ = _redis_limiter(results=[0, 1, 3, True, [("m", 950.0)]])
    _, remaining, _ = _run(limiter.check("k", 5, 60))
    assert remaining == 2  # from count 3, not from results[3]


def test_check_redis_blocks_when_count_exceeds_limit():
    # count 7 > limit 5: blocked, and max(0, 5 - 7) clamps remaining to 0. Pins
    # `count <= limit` (False here) and the max() lower bound.
    limiter, _ = _redis_limiter(results=[0, 1, 7, True, [("m", 950.0)]])
    allowed, remaining, _ = _run(limiter.check("k", 5, 60))
    assert allowed is False
    assert remaining == 0


def test_check_redis_allows_when_count_equals_limit():
    # count == limit must still be allowed: pins `<=`->`<`.
    limiter, _ = _redis_limiter(results=[0, 1, 5, True, [("m", 950.0)]])
    allowed, remaining, _ = _run(limiter.check("k", 5, 60))
    assert allowed is True
    assert remaining == 0  # max(0, 5 - 5)


def test_check_redis_reset_falls_back_to_now_when_no_oldest_entry():
    # Empty zrange -> `if oldest_entry` is False -> reset_at stays int(now + window).
    limiter, _ = _redis_limiter(results=[0, 1, 1, True, []])
    _, _, reset_at = _run(limiter.check("k", 5, 60))
    assert reset_at == 1_060  # int(1000 + 60); kills the L59 `+`->`-`


def test_check_redis_reset_reads_oldest_entry_score():
    # Non-empty zrange -> reset_at = int(float(oldest_entry[0][1]) + window). Pins
    # the [0][1] indexing and the `+ window_seconds`.
    limiter, _ = _redis_limiter(results=[0, 1, 1, True, [("m", 900.0)]])
    _, _, reset_at = _run(limiter.check("k", 5, 60))
    assert reset_at == 960  # int(900 + 60)


def test_check_redis_pipeline_commands_and_arguments():
    limiter, redis_double = _redis_limiter(results=[0, 1, 1, True, [("m", 950.0)]])
    _run(limiter.check("k", 5, 60))
    pipe = redis_double.pipelines[0]
    names = [call[0] for call in pipe.calls]
    assert names == ["zremrangebyscore", "zadd", "zcard", "expire", "zrange"]

    zrem = pipe.calls[0]
    assert zrem[1][0] == "k"
    # float("-inf") == float("-INF"): a case mutation of the literal is an
    # equivalent mutant (float() is case-insensitive), so pin the value not text.
    assert zrem[1][1] == float("-inf")
    assert zrem[1][2] == 940.0  # now - window_seconds = 1000 - 60

    assert pipe.calls[1][1][0] == "k"  # zadd keyed by the rate-limit key, not None
    zadd_mapping = pipe.calls[1][1][1]
    assert list(zadd_mapping.values()) == [1_000.0]  # score == now
    only_member = next(iter(zadd_mapping))
    assert only_member.startswith("1000.0:")  # f"{now}:{uuid}"

    assert pipe.calls[2] == ("zcard", ("k",))

    expire_call = pipe.calls[3]
    assert expire_call == ("expire", ("k", 120))  # window_seconds * 2

    zrange_call = pipe.calls[4]
    assert zrange_call == ("zrange", ("k", 0, 0), {"withscores": True})


def test_check_redis_branch_is_taken_over_local(monkeypatch):
    # With a non-None _redis, check() must use the redis path (reset from the
    # scripted oldest entry), not _check_local. Kills `if self._redis is None`
    # -> `is not None`.
    monkeypatch.setattr(rate_limiter_module, "logger", _LoggerSpy())
    limiter, _ = _redis_limiter(results=[0, 1, 1, True, [("m", 900.0)]])
    _, _, reset_at = _run(limiter.check("k", 5, 60))
    assert reset_at == 960  # redis-derived; _check_local would give 1060


# --------------------------------------------------------------------------- #
# check(): redis failure -> fail closed to the per-process cap (audit_28 #7).
# --------------------------------------------------------------------------- #


def test_check_redis_failure_fails_closed_to_local_cap(monkeypatch):
    spy = _LoggerSpy()
    monkeypatch.setattr(rate_limiter_module, "logger", spy)
    redis_double = _ScriptedRedis(raise_on_execute=RuntimeError("redis down"))
    limiter = RateLimiter(redis_client=redis_double, time_source=lambda: 1_000.0)

    allowed, remaining, reset_at = _run(limiter.check("k", 2, 60))
    # Fail CLOSED to a per-process cap (allowed but counted), not fail open.
    assert allowed is True
    assert remaining == 1
    assert reset_at == 1_060
    assert spy.warning_calls == [
        ("rate_limiter_unavailable", {"operation": "check", "error": "redis down"})
    ]


def test_check_redis_failure_local_cap_is_actually_enforced(monkeypatch):
    monkeypatch.setattr(rate_limiter_module, "logger", _LoggerSpy())
    redis_double = _ScriptedRedis(raise_on_execute=RuntimeError("redis down"))
    limiter = RateLimiter(redis_client=redis_double, time_source=lambda: 1_000.0)

    _run(limiter.check("k", 2, 60))
    _run(limiter.check("k", 2, 60))
    allowed, remaining, _ = _run(limiter.check("k", 2, 60))
    assert allowed is False  # the local fallback enforces the cap of 2
    assert remaining == 0


def test_check_redis_failure_fallback_is_isolated_per_key(monkeypatch):
    # The except-branch fallback must also forward the real key to _check_local
    # (the twin of the local-branch mutant): distinct keys stay independent even
    # when Redis is down.
    monkeypatch.setattr(rate_limiter_module, "logger", _LoggerSpy())
    redis_double = _ScriptedRedis(raise_on_execute=RuntimeError("redis down"))
    limiter = RateLimiter(redis_client=redis_double, time_source=lambda: 1_000.0)
    _run(limiter.check("a", 1, 60))
    a_blocked, _, _ = _run(limiter.check("a", 1, 60))
    b_allowed, b_remaining, _ = _run(limiter.check("b", 1, 60))
    assert a_blocked is False
    assert b_allowed is True
    assert b_remaining == 0
