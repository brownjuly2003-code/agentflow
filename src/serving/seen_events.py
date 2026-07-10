"""Bounded, insertion-ordered seen-set for journal/event dedup (issue #183).

The process-wide journal consumers (webhook dispatcher, metric-cache
controller) dedup events with in-memory "seen" sets. A plain ``set`` grows
with the journal forever — the S11 soak measured the API process at 1.67 GB
RSS after 4 h of steady ingestion, and every event id ever scanned or pushed
was part of that retained growth. This container caps the dedup memory
instead: adding beyond ``maxlen`` evicts the oldest entry.

Eviction is safe for both consumers because neither uses the set for
correctness-critical dedup: webhook enqueue is idempotent on its primary key
(a re-scanned event never duplicates a delivery), and a redundant metric-cache
invalidate only drops keys that repopulate on the next read.

Re-adding an existing key refreshes its position (moves it to the young end),
so keys that every scan pass re-confirms are not evicted by unrelated churn —
without the refresh, a busy push feed could evict the scan window's ids and
turn every fallback scan into a spurious "new events" signal.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, MutableSet


class BoundedSeenSet(MutableSet[str]):
    """A string set with a size cap and FIFO-with-refresh eviction.

    Compares like a set (``collections.abc.Set`` semantics), so call sites
    and tests can keep using set literals for equality and subset checks.
    """

    def __init__(self, maxlen: int = 10_000, iterable: Iterable[str] = ()) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be >= 1")
        self._maxlen = maxlen
        self._data: dict[str, None] = {}
        for item in iterable:
            self.add(item)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @classmethod
    def _from_iterable(cls, it: Iterable[str]) -> set[str]:
        # Set-algebra operators (&, |, -) build their result through this
        # hook; a plain set is the right result type — the cap belongs to the
        # long-lived instance, not to derived values.
        return set(it)

    def add(self, value: str) -> None:
        if value in self._data:
            del self._data[value]  # re-add refreshes insertion order
        self._data[value] = None
        while len(self._data) > self._maxlen:
            del self._data[next(iter(self._data))]

    def discard(self, value: str) -> None:
        self._data.pop(value, None)

    def clear(self) -> None:
        self._data.clear()

    def __contains__(self, value: object) -> bool:
        return value in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(maxlen={self._maxlen}, items={list(self._data)!r})"
