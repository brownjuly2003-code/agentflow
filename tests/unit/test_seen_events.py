"""Unit coverage for ``BoundedSeenSet`` (issue #183).

The journal consumers dedup with in-memory seen-sets; this container caps
that memory. The tests pin the three properties the consumers rely on:
set-compatible semantics (their tests and call sites use set literals),
FIFO eviction at the cap, and refresh-on-re-add so entries every scan pass
re-confirms are not evicted by unrelated churn.
"""

from __future__ import annotations

import pytest

from src.serving.seen_events import BoundedSeenSet


def test_acts_like_a_set() -> None:
    seen = BoundedSeenSet(maxlen=10)
    seen.add("a")
    seen.add("b")
    seen.add("a")  # duplicate add is a no-op for membership

    assert "a" in seen
    assert "missing" not in seen
    assert len(seen) == 2
    assert seen == {"a", "b"}
    assert {"a"} <= seen
    assert sorted(seen) == ["a", "b"]

    seen.discard("a")
    seen.discard("never-there")  # discard of a missing key must not raise
    assert seen == {"b"}

    seen.clear()
    assert len(seen) == 0


def test_set_algebra_returns_plain_sets() -> None:
    seen = BoundedSeenSet(maxlen=10, iterable=["a", "b"])
    assert (seen | {"c"}) == {"a", "b", "c"}
    assert (seen & {"b", "c"}) == {"b"}
    assert (seen - {"a"}) == {"b"}


def test_cap_evicts_oldest_first() -> None:
    seen = BoundedSeenSet(maxlen=3)
    for key in ("e1", "e2", "e3", "e4", "e5"):
        seen.add(key)

    assert len(seen) == 3
    assert seen == {"e3", "e4", "e5"}
    assert "e1" not in seen


def test_re_add_refreshes_position_against_eviction() -> None:
    seen = BoundedSeenSet(maxlen=3)
    seen.add("scan-window-id")
    seen.add("push-1")
    seen.add("push-2")
    # The scan re-confirms its id every pass; the refresh must keep it alive
    # while newer push churn evicts around it.
    seen.add("scan-window-id")
    seen.add("push-3")

    assert "scan-window-id" in seen
    assert "push-1" not in seen  # oldest non-refreshed entry went first


def test_maxlen_must_be_positive() -> None:
    with pytest.raises(ValueError):
        BoundedSeenSet(maxlen=0)
