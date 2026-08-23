"""Shared plumbing for the embedded (DuckDB) control-plane repositories.

Carries what every capability repository (webhook, alert, outbox/replay,
usage/audit) inherits: the live serving-engine connection, the config-file
path providers, and the per-path usage-db connection registry. Split out of
the single-module ``embedded.py`` adapter (audit F-08) with bodies moved
verbatim; ``embedded.py`` still assembles ``EmbeddedControlPlaneStore`` and
stays the public import surface and the tests' monkeypatch seam
(``embedded.connect_duckdb``, ``embedded._USAGE_CONNECTIONS``).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import duckdb
import structlog

from .store import ControlPlaneStore

logger = structlog.get_logger()

# One owning DuckDB connection per usage-db path, kept open for the life of the
# process; callers work through `.cursor()` children of it.
#
# Every authenticated request writes an `api_usage` row from a worker thread,
# and the analytics/admin routers build a throwaway store per request. Opening
# a fresh `duckdb.connect(path)` for each of those races DuckDB's instance
# cache: when the last connection to a file closes while another is opening,
# the file is momentarily attached by two database instances and DuckDB raises
# `BinderException: Unique file handle conflict`. That escaped the auth
# middleware as a 500 on requests which had otherwise succeeded (2026-07-09
# Load Test: 19 of 1712). Holding the connection open removes the
# destroy/recreate window; a cursor is DuckDB's thread-safe unit, the same
# shape `DuckDBPool` uses for the serving database.
_USAGE_CONNECTIONS: dict[str, duckdb.DuckDBPyConnection] = {}

_USAGE_CONNECTIONS_LOCK = threading.Lock()


def _usage_connection(path: str) -> duckdb.DuckDBPyConnection:
    conn = _USAGE_CONNECTIONS.get(path)
    if conn is not None:
        return conn
    with _USAGE_CONNECTIONS_LOCK:
        conn = _USAGE_CONNECTIONS.get(path)
        if conn is None:
            # Resolved through the `embedded` module namespace at call time:
            # tests monkeypatch `embedded.connect_duckdb` to inject flaky
            # connections, and that seam predates this split (audit F-08).
            from . import embedded

            conn = embedded.connect_duckdb(path)
            _USAGE_CONNECTIONS[path] = conn
    return conn


def _drop_usage_connection(path: str) -> None:
    """Forget a connection whose instance may be unusable, so the next caller
    reopens it instead of inheriting the failure."""
    with _USAGE_CONNECTIONS_LOCK:
        conn = _USAGE_CONNECTIONS.pop(path, None)
    if conn is not None:
        try:
            conn.close()
        except duckdb.Error:  # pragma: no cover - closing an already-dead handle
            pass


def close_usage_connections() -> None:
    """Close every cached usage-db connection. Tests that delete their temp
    database files call this first — Windows will not unlink an open file."""
    with _USAGE_CONNECTIONS_LOCK:
        connections = list(_USAGE_CONNECTIONS.values())
        _USAGE_CONNECTIONS.clear()
    for conn in connections:
        try:
            conn.close()
        except duckdb.Error:  # pragma: no cover
            pass


class EmbeddedControlPlaneBase(ControlPlaneStore):
    """Provider wiring and connection plumbing shared by the embedded
    capability repositories. ``embedded.EmbeddedControlPlaneStore`` is the
    assembled adapter; see its docstring for the resolution contract."""

    def __init__(
        self,
        conn_provider: Callable[[], duckdb.DuckDBPyConnection] | None = None,
        *,
        alert_rules_path_provider: Callable[[], Path] | None = None,
        usage_db_path_provider: Callable[[], Path | str] | None = None,
        webhook_registrations_path_provider: Callable[[], Path] | None = None,
    ) -> None:
        self._conn_provider = conn_provider
        self._alert_rules_path_provider = alert_rules_path_provider
        self._usage_db_path_provider = usage_db_path_provider
        self._webhook_registrations_path_provider = webhook_registrations_path_provider
        # Set once by _ensure_usage_db_connection's IOException fallback and
        # then sticky for the rest of this store's lifetime — mirrors the
        # pre-port code permanently reassigning `AuthManager.db_path` in
        # place (module docstring: usage/session state is never on the
        # shared conn_provider connection, so this override never touches
        # the app's query engine).
        self._usage_db_path_override: Path | None = None

    @property
    def _alert_rules_path(self) -> Path:
        if self._alert_rules_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without an "
                "alert_rules_path_provider; alert-rule repository methods "
                "are unavailable."
            )
        return self._alert_rules_path_provider()

    @property
    def _webhook_registrations_path(self) -> Path:
        if self._webhook_registrations_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "webhook_registrations_path_provider; webhook-registration "
                "repository methods are unavailable."
            )
        return self._webhook_registrations_path_provider()

    @property
    def _conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "conn_provider; webhook/alert/outbox methods are unavailable."
            )
        return self._conn_provider()

    @property
    def _usage_db_path(self) -> Path:
        if self._usage_db_path_override is not None:
            return self._usage_db_path_override
        if self._usage_db_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "usage_db_path_provider; usage/session methods are "
                "unavailable."
            )
        return Path(self._usage_db_path_provider())

    # --- API usage accounting -------------------------------------------------

    def _usage_cursor(self) -> duckdb.DuckDBPyConnection:
        """A cursor on the process-wide connection for this store's usage db.

        Drop-in for the old per-call ``connect_duckdb``: callers still own the
        handle and still ``close()`` it, but closing a cursor leaves the owning
        connection — and therefore the DuckDB instance — alive. The path is
        resolved on every call so the Windows fallback in
        ``ensure_usage_schema`` (which swaps ``_usage_db_path_override``
        mid-flight) lands on the new file.
        """
        path = str(self._usage_db_path)
        try:
            return _usage_connection(path).cursor()
        except duckdb.Error:
            _drop_usage_connection(path)
            raise
