"""Event-driven OLTP -> raw-vault promotion via PostgreSQL LISTEN/NOTIFY.

An AFTER INSERT/UPDATE trigger on each ``ops_<branch>`` table issues
``pg_notify`` on the ``dv2_vault_refresh`` channel (see
``freshness_listen_notify.sql``). This listener LISTENs on that channel and runs
the idempotent promotion (``promote_to_raw_vault_pg.sql``) as soon as a change
lands, measuring the OLTP-change -> vault-visible lag. Freshness is push driven,
not polled.

This is the PostgreSQL-native equivalent of the ClickHouse
``MaterializedPostgreSQL`` push-CDC (``cdc_setup.sql``): the same "push, not
poll" property, but with no replication slot, no WAL consumer, and no second
engine -- the vault is in the same PostgreSQL instance, so a NOTIFY plus an
idempotent ``INSERT ... SELECT`` is the whole mechanism.

psycopg is guarded exactly like ``loaders/pg_vault_writer.py``: it is only needed
for a live run, never for the no-Docker unit tests, which drive the pure
functions (:func:`parse_notification`, :func:`lag_ms`, :func:`process_notifications`)
with fake notifications.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # psycopg 3; absent is fine until a live listen is actually attempted.
    import psycopg

    _PSYCOPG_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - hosts without psycopg
    psycopg = None  # type: ignore[assignment]
    _PSYCOPG_IMPORT_ERROR = exc


CHANNEL = "dv2_vault_refresh"
PROMOTE_SQL_PATH = Path(__file__).resolve().parent / "promote_to_raw_vault_pg.sql"


@dataclass(frozen=True)
class ChangeEvent:
    """One OLTP change announced on the ``dv2_vault_refresh`` channel."""

    branch: str
    source_table: str
    op: str
    emitted_at: float  # epoch seconds from clock_timestamp() at emit


@dataclass(frozen=True)
class Measurement:
    """A promoted change event with its emit -> vault-visible lag."""

    event: ChangeEvent
    lag_ms: float


def parse_notification(payload: str) -> ChangeEvent:
    """Parse one ``dv2_vault_refresh`` JSON payload into a :class:`ChangeEvent`.

    Raises :class:`ValueError` on a malformed payload (missing keys, wrong
    types, or non-JSON) so a bad notification never silently runs a promotion.
    """
    try:
        data = json.loads(payload)
        return ChangeEvent(
            branch=str(data["branch"]),
            source_table=str(data["source_table"]),
            op=str(data["op"]),
            emitted_at=float(data["emitted_at"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed dv2_vault_refresh payload: {payload!r}") from exc


def lag_ms(event: ChangeEvent, observed_at: float) -> float:
    """Emit -> observation lag in milliseconds, floored at 0.

    ``observed_at`` is epoch seconds sampled right after the vault reflects the
    change. It MUST come from the same clock as the trigger's
    ``clock_timestamp()`` -- i.e. the PostgreSQL server clock (see
    :func:`db_now`) -- otherwise host/container clock skew swamps the real
    latency. The floor at 0 only guards sub-millisecond rounding, not skew.
    """
    return max(0.0, (observed_at - event.emitted_at) * 1000.0)


def process_notifications(
    notifications: Iterable[tuple[str, str]],
    run_promotion: Callable[[ChangeEvent], None],
    now: Callable[[], float] = time.time,
) -> list[Measurement]:
    """Promote per change event and return the lag measurements.

    ``notifications`` yields ``(channel, payload)`` pairs; foreign channels are
    skipped. ``run_promotion`` performs the idempotent promotion (re-running it
    is a no-op, so a duplicate notification cannot double-insert); ``now``
    samples the observation time once the promotion has made the change visible.

    Pure -- no psycopg -- which is exactly what the no-Docker unit tests drive.
    """
    measurements: list[Measurement] = []
    for channel, payload in notifications:
        if channel != CHANNEL:
            continue
        event = parse_notification(payload)
        run_promotion(event)
        measurements.append(Measurement(event=event, lag_ms=lag_ms(event, now())))
    return measurements


# --- live wiring (psycopg) ---------------------------------------------------


def _require_psycopg() -> Any:
    if psycopg is None:
        raise RuntimeError(
            "psycopg is required for a live listen. Install psycopg[binary] "
            f"(import failed: {_PSYCOPG_IMPORT_ERROR})."
        )
    return psycopg


def listen(connection: Any) -> None:
    """Issue ``LISTEN dv2_vault_refresh`` on an (autocommit) connection."""
    connection.execute(f"LISTEN {CHANNEL}")


def db_now(connection: Any) -> float:
    """Sample the PostgreSQL server clock (epoch seconds).

    The lag must be measured on the same clock that stamped the emit, so the
    observation reads ``clock_timestamp()`` from the database rather than the
    client's wall clock -- on a containerised single-node demo the two differ by
    the VM's clock drift, which would otherwise dominate the reading.
    """
    cur = connection.execute("SELECT extract(epoch FROM clock_timestamp())")
    value = float(cur.fetchone()[0])
    connection.commit()
    return value


def iter_notifications(
    connection: Any, timeout: float, stop_after: int | None = None
) -> Iterator[tuple[str, str]]:
    """Yield ``(channel, payload)`` from psycopg's notification generator.

    A thin adapter so :func:`process_notifications` stays driver-agnostic.
    ``timeout`` bounds the wait; ``stop_after`` (if set) stops once that many
    notifications have been yielded.
    """
    _require_psycopg()
    seen = 0
    for note in connection.notifies(timeout=timeout, stop_after=stop_after):
        yield note.channel, note.payload
        seen += 1
        if stop_after is not None and seen >= stop_after:
            break


def run_once(
    listen_conn: Any,
    writer_conn: Any,
    *,
    timeout: float = 10.0,
    stop_after: int = 1,
    promote_sql: str | None = None,
    now: Callable[[], float] | None = None,
) -> list[Measurement]:
    """Wait for changes, promote each, and return lag measurements.

    ``listen_conn`` must already have run :func:`listen`; ``writer_conn`` runs
    the idempotent promotion. The observation clock defaults to the PostgreSQL
    server clock (:func:`db_now` on ``writer_conn``) so the lag is skew-free;
    pass ``now`` only to override it. Wires the real psycopg notification stream
    into :func:`process_notifications`; the single-node Mac smoke exercises this.
    """
    sql = promote_sql if promote_sql is not None else PROMOTE_SQL_PATH.read_text(encoding="utf-8")
    if now is None:
        now = lambda: db_now(writer_conn)  # noqa: E731 - DB-clock sampler for skew-free lag

    def _promote(_event: ChangeEvent) -> None:
        writer_conn.execute(sql)
        writer_conn.commit()

    return process_notifications(
        iter_notifications(listen_conn, timeout=timeout, stop_after=stop_after),
        _promote,
        now=now,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI listener daemon: LISTEN, promote on every change, print lag."""
    import argparse

    parser = argparse.ArgumentParser(description="DV2 OLTP->vault LISTEN/NOTIFY freshness listener")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait per cycle")
    parser.add_argument(
        "--stop-after", type=int, default=None, help="exit after N changes (default: run forever)"
    )
    args = parser.parse_args(argv)

    pg = _require_psycopg()
    listen_conn = pg.connect(args.dsn, autocommit=True)
    writer_conn = pg.connect(args.dsn)
    try:
        listen(listen_conn)
        remaining = args.stop_after
        while remaining is None or remaining > 0:
            batch = run_once(
                listen_conn,
                writer_conn,
                timeout=args.timeout,
                stop_after=remaining if remaining is not None else 1,
            )
            for m in batch:
                print(
                    f"promoted branch={m.event.branch} table={m.event.source_table} "
                    f"op={m.event.op} lag={m.lag_ms:.1f}ms"
                )
            if remaining is not None:
                remaining -= len(batch)
            if not batch:
                break  # timeout with nothing to do
    finally:
        listen_conn.close()
        writer_conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
