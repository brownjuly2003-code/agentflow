"""Off-request-path writer for ``api_usage`` rows.

Why this exists
---------------

Every authenticated request used to write its own ``api_usage`` row before the
response was produced. The embedded store serializes writers and commits each
row, so that write put an fsync on the critical path of every request and
capped the whole API at ``1 / commit_latency`` requests per second.

That cap is why the ``Load Test`` workflow read as bimodal. The load client is
closed-loop (15 users, 0.1-0.5 s think time), so it has two equilibria: an
unsaturated one bounded by think time (~46 rps, p50 7 ms), and a saturated one
pinned at ``rps = 1 / commit_latency``. A runner whose disk pushed the commit
past ~20 ms tipped the run onto the saturated branch, where three separate red
runs landed within 1.7% of each other (29.4 / 29.1 / 28.9 rps) while green runs
spread across 37-46. Measured, not inferred:
``docs/perf/usage-write-bifurcation-2026-07-09.md``.

The contract this keeps
-----------------------

Accounting is a side-channel. It already could not fail a request (the store
raises on exhausted retries and the caller counts the drop). It must not
*pace* one either. So the request enqueues a row and returns; a single writer
thread drains the queue in batches, one commit per batch.

What that trades
----------------

Durability moves from "the row is committed before the response" to "the row is
committed shortly after". A crash loses at most the queued rows. ``api_usage``
feeds one admin read (``GET /v1/admin/usage``); it is not billing and not rate
limiting, and rows were already droppable on exhausted retries. Reads that must
see their own writes call ``flush``; the API lifespan closes the writer on
shutdown.

Backpressure is bounded, never blocking: a full queue drops the row and counts
it in ``agentflow_usage_rows_dropped_total``. Dropping a counter row is
strictly better than stalling the request it was counting -- that stall is the
bug this module exists to remove.
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Protocol

import structlog

from src.serving.api.metrics import USAGE_RECORD_FAILURES, USAGE_ROWS_DROPPED
from src.serving.control_plane.store import UsageRow

if TYPE_CHECKING:
    from src.serving.control_plane.store import ControlPlaneStore

logger = structlog.get_logger(__name__)

DEFAULT_MAX_QUEUE = 10_000
DEFAULT_MAX_BATCH = 256
_SHUTDOWN = object()


class AuditPublisher(Protocol):
    def publish(self, payload: dict) -> object: ...


class UsageWriter:
    """Drains queued ``api_usage`` rows on one background thread.

    The thread starts on the first ``submit`` so that constructing an
    ``AuthManager`` — which tests do constantly — costs no thread.
    """

    def __init__(
        self,
        store: ControlPlaneStore,
        audit_publisher: AuditPublisher | None = None,
        *,
        max_queue: int = DEFAULT_MAX_QUEUE,
        max_batch: int = DEFAULT_MAX_BATCH,
    ) -> None:
        self._store = store
        self._audit_publisher = audit_publisher
        self._max_batch = max_batch
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._closed = False

    # -- request path -----------------------------------------------------

    def submit(self, row: UsageRow) -> bool:
        """Enqueue one row. Never blocks, never raises.

        Returns ``False`` when the row was dropped (queue full, or the writer
        is closed); the caller has already served its request either way.
        """
        if self._closed:
            return False
        self._ensure_thread()
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            USAGE_ROWS_DROPPED.inc()
            logger.warning("api_usage_queue_full", endpoint=row.endpoint, tenant=row.tenant)
            return False
        return True

    # -- lifecycle --------------------------------------------------------

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is not None:
                return
            thread = threading.Thread(target=self._run, name="agentflow-usage-writer", daemon=True)
            thread.start()
            self._thread = thread

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until every queued row has been written (or dropped).

        Returns ``False`` on timeout. Callers that must read their own writes
        (``GET /v1/admin/usage``, tests) go through here.
        """
        if self._thread is None:
            return True
        done = threading.Event()
        try:
            self._queue.put_nowait(done)
        except queue.Full:
            return False
        return done.wait(timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Flush, stop the thread, and refuse further rows."""
        if self._closed:
            return
        self._closed = True
        thread = self._thread
        if thread is None:
            return
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:  # pragma: no cover - a full queue still drains
            pass
        thread.join(timeout)
        self._thread = None

    # -- writer thread ----------------------------------------------------

    def _run(self) -> None:
        while True:
            first = self._queue.get()
            if first is _SHUTDOWN:
                return
            batch, waiters, stop = self._drain(first)
            if batch:
                self._write(batch)
            for waiter in waiters:
                waiter.set()
            if stop:
                return

    def _drain(self, first: object) -> tuple[list[UsageRow], list[threading.Event], bool]:
        """Take ``first`` plus whatever else is already queued, up to one batch.

        Flush markers and the shutdown sentinel ride the same queue, so a
        marker is only signalled after every row queued ahead of it is written.
        """
        batch: list[UsageRow] = []
        waiters: list[threading.Event] = []
        stop = False
        item = first
        while True:
            if item is _SHUTDOWN:
                stop = True
            elif isinstance(item, threading.Event):
                waiters.append(item)
            else:
                batch.append(item)  # type: ignore[arg-type]
            if stop or len(batch) >= self._max_batch:
                break
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
        return batch, waiters, stop

    def _write(self, batch: list[UsageRow]) -> None:
        try:
            self._store.record_api_usage_batch(batch)
        except Exception:
            # The store exhausted its retries. Count the rows we dropped and
            # skip their audit publish, exactly as the synchronous path did:
            # a publish must never claim a row that was never inserted.
            USAGE_RECORD_FAILURES.inc(len(batch))
            logger.warning("api_usage_batch_dropped", rows=len(batch), exc_info=True)
            return
        if self._audit_publisher is None:
            return
        for row in batch:
            try:
                self._audit_publisher.publish(
                    {
                        "event_type": "api_usage",
                        "tenant": row.tenant,
                        "key_name": row.key_name,
                        "endpoint": row.endpoint,
                        "key_id": row.key_id,
                        "key_slot": row.key_slot,
                    }
                )
            except Exception:
                logger.warning(
                    "audit_publish_failed",
                    tenant=row.tenant,
                    endpoint=row.endpoint,
                    key_id=row.key_id,
                    exc_info=True,
                )
