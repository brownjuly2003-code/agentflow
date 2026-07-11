"""Journal reads (``pipeline_events``), routed through the active serving backend.

`/v1/lineage`, `/v1/slo` and the health collector each opened their own DuckDB
cursor and read the embedded store directly, whatever ``SERVING_BACKEND`` said
(audit P0-3). On the ClickHouse profile that cut the API in half: `/v1/entity`
and `/v1/metrics` answered from ClickHouse while lineage, SLO and health
answered from a DuckDB that held nothing but demo rows — and `/v1/health`
reported on a store nobody was reading. A plausible wrong answer is worse than
an error, so every read here goes through ``ServingBackend`` instead.

The SQL is DuckDB-flavoured, because that is the dialect the ClickHouse backend
transpiles *from* (sqlglot, duckdb → clickhouse). Two constraints follow:

* Stay inside the constructs that survive the transpile. ``COUNT(*) FILTER
  (WHERE ...)`` does — the backend rewrites it to ``countIf`` — as does
  ``quantile_cont`` (rewritten to the parametric ``quantile(q)(col)``) and
  ``NOW() - INTERVAL '7 days'``, which the shipped metric templates already rely
  on. ``EXTRACT(EPOCH FROM ...)`` does not, so ages are computed in Python from
  timestamps the store hands back.
* Values bind as ``?`` on a backend that binds and are escaped as literals on
  one that does not — ClickHouse's ``execute(params=...)`` is a documented
  no-op. Same split the semantic layer already makes (``use_query_params``), so
  the DuckDB path keeps its parameter binding and nothing regresses to string
  building. Only identifiers, chosen from a live schema probe, are interpolated.

Freshness is measured against the *store's own clock*. The journal keeps naive
timestamps in different zones on the two stores — local on DuckDB, UTC on
ClickHouse — so ``NOW()`` is selected alongside the value and the subtraction
happens in Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

from src.serving.backends import BackendMissingTableError, ServingBackend
from src.serving.semantic_layer.sql_literals import quote_sql_literal

logger = structlog.get_logger()

JOURNAL_TABLE = "pipeline_events"

# The journal's clock column, newest schema first. Both are naive and
# store-local; `_coerce` never converts a zone.
_TIME_COLUMNS = ("processed_at", "created_at")

# Rows whose topic is the warehouse stage clock rather than the ingestion trail
# (ops-surfaces-spec.md §1.1). Excluded from lineage so they cannot hijack
# source_topic / earliest_at — Order 360 shows stage history instead.
_STAGE_TRAIL_TOPIC = "orders.status"


def coerce_journal_datetime(value: object) -> datetime | None:
    """Parse a journal timestamp.

    DuckDB hands back ``datetime`` objects; ClickHouse's JSON transport hands
    back ``'YYYY-MM-DD HH:MM:SS'`` strings. Both are naive and store-local, and
    nothing here converts between zones — see the module docstring.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, str):
        text = value.strip().replace("T", " ").split(".", 1)[0]
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class EventCounts:
    """Events in a window, and how many of them failed."""

    total: int
    errors: int


@dataclass(frozen=True)
class Freshness:
    """The newest journal row in a window, against the store's own clock."""

    latest_event_at: datetime | None
    store_now: datetime | None

    @property
    def age_seconds(self) -> float | None:
        if self.latest_event_at is None or self.store_now is None:
            return None
        return max(0.0, (self.store_now - self.latest_event_at).total_seconds())


def _where(*predicates: str | None) -> str:
    parts = [predicate for predicate in predicates if predicate]
    return f" WHERE {' AND '.join(parts)}" if parts else ""


class JournalReader:
    """Reads ``pipeline_events`` through whichever backend is serving."""

    def __init__(self, backend: ServingBackend) -> None:
        self._backend = backend
        # ClickHouse's execute() ignores params; DuckDB binds them. Mirrors
        # `use_query_params` in the semantic layer rather than inventing a
        # second way to ask the same question.
        self._binds_parameters = backend.name == "duckdb"
        self._columns: set[str] | None = None

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def backend_health(self) -> dict:
        """The serving store's own health payload — the store the API reads."""
        return self._backend.health()

    def columns(self) -> set[str]:
        """The journal's live column set — empty when the store has no journal.

        Cached: the schema does not change under a running process, and the
        probe is one round trip on ClickHouse.
        """
        if self._columns is None:
            try:
                self._columns = self._backend.table_columns(JOURNAL_TABLE)
            except BackendMissingTableError:
                self._columns = set()
        return self._columns

    def refresh_columns(self) -> None:
        """Forget the cached schema probe (the journal gained a column)."""
        self._columns = None

    def time_column(self) -> str | None:
        columns = self.columns()
        return next((name for name in _TIME_COLUMNS if name in columns), None)

    # -- query building ----------------------------------------------------

    def _value(self, value: object, params: list[object]) -> str:
        """A bound placeholder where the backend binds, a quoted literal where
        it does not."""
        if self._binds_parameters:
            params.append(value)
            return "?"
        return quote_sql_literal(value)

    def _tenant_predicate(self, tenant_id: str | None, params: list[object]) -> str | None:
        """Scope a journal read to one tenant.

        A tenant other than ``default`` reading a journal that has no
        ``tenant_id`` column gets ``1 = 0`` — nothing — rather than the whole
        journal. That is the difference between an empty answer and another
        tenant's rows.
        """
        if tenant_id is None:
            return None
        if "tenant_id" in self.columns():
            return f"COALESCE(tenant_id, 'default') = {self._value(tenant_id, params)}"
        if tenant_id != "default":
            return "1 = 0"
        return None

    def _window_predicate(self, time_column: str, window: str | None) -> str | None:
        if window is None:
            return None
        # The one value inlined on both backends rather than bound. It is never
        # request data — `f"{window_days} days"` off an int in config/slo.yaml,
        # or a literal at the call site — and no form both binds and translates:
        # `INTERVAL ?` is a DuckDB syntax error, while `CAST(? AS INTERVAL)`,
        # the form that does bind, has no ClickHouse translation.
        # `NOW() - INTERVAL '7 days'` is what the shipped metric templates
        # already send to both stores, and the store evaluates NOW(), so the
        # window is anchored to the store's own clock.
        return f"{time_column} >= NOW() - INTERVAL {quote_sql_literal(window)}"

    def _rows(self, sql: str, params: list[object]) -> list[dict]:
        try:
            return self._backend.execute(sql, params or None)
        except BackendMissingTableError:
            # An external store nobody provisioned. Readiness says so loudly;
            # a read surface answers "nothing yet" instead of a 500.
            logger.warning("journal_table_missing", backend=self._backend.name)
            return []

    # -- reads -------------------------------------------------------------

    def lineage_events(
        self,
        *,
        entity_type: str,
        entity_id: str,
        tenant_id: str | None,
    ) -> list[dict]:
        """The ingestion trail for one entity, oldest first."""
        columns = self.columns()
        time_column = self.time_column()
        if "entity_id" not in columns or time_column is None:
            return []

        params: list[object] = []
        select_columns = [
            "event_id",
            "topic",
            f"{time_column} AS processed_at",
            (
                "COALESCE(tenant_id, 'default') AS tenant_id"
                if "tenant_id" in columns
                else "'default' AS tenant_id"
            ),
            "event_type" if "event_type" in columns else "NULL AS event_type",
            "entity_id",
            "latency_ms" if "latency_ms" in columns else "NULL AS latency_ms",
        ]
        predicates: list[str | None] = [f"entity_id = {self._value(entity_id, params)}"]
        if "entity_type" in columns:
            predicates.append(f"entity_type = {self._value(entity_type, params)}")
        if "topic" in columns:
            predicates.append(f"topic != {self._value(_STAGE_TRAIL_TOPIC, params)}")
        predicates.append(self._tenant_predicate(tenant_id, params))

        sql = (
            # Identifiers come from the live schema probe above; every value is
            # bound or _quote_literal-escaped by _value().
            f"SELECT {', '.join(select_columns)} "  # nosec B608  # noqa: S608
            f"FROM {JOURNAL_TABLE}"
            f"{_where(*predicates)} "
            f"ORDER BY {time_column} ASC"
        )
        return self._rows(sql, params)

    def freshness(self, *, window: str | None = None, tenant_id: str | None = None) -> Freshness:
        """The newest journal row and the store's clock, for subtraction here."""
        time_column = self.time_column()
        if time_column is None:
            return Freshness(latest_event_at=None, store_now=None)

        params: list[object] = []
        clause = _where(
            self._window_predicate(time_column, window),
            self._tenant_predicate(tenant_id, params),
        )
        sql = (
            # time_column comes from the schema probe's fixed allowlist.
            f"SELECT MAX({time_column}) AS latest, NOW() AS store_now "  # nosec B608  # noqa: S608
            f"FROM {JOURNAL_TABLE}{clause}"
        )
        rows = self._rows(sql, params)
        if not rows:
            return Freshness(latest_event_at=None, store_now=None)
        row = rows[0]
        return Freshness(
            latest_event_at=coerce_journal_datetime(row.get("latest")),
            store_now=coerce_journal_datetime(row.get("store_now")),
        )

    def latency_quantile_ms(
        self,
        *,
        quantile: float,
        window: str,
        tenant_id: str | None = None,
    ) -> float | None:
        columns = self.columns()
        time_column = self.time_column()
        if "latency_ms" not in columns or time_column is None:
            return None

        params: list[object] = []
        clause = _where(
            self._window_predicate(time_column, window),
            self._tenant_predicate(tenant_id, params),
            "latency_ms IS NOT NULL",
        )
        sql = (
            # quantile is a float from the SLO config, formatted here; the
            # ClickHouse backend rewrites quantile_cont to quantile(q)(col).
            f"SELECT quantile_cont(latency_ms, {quantile:g}) AS value "  # nosec B608  # noqa: S608
            f"FROM {JOURNAL_TABLE}{clause}"
        )
        rows = self._rows(sql, params)
        value = rows[0].get("value") if rows else None
        return float(value) if value is not None else None

    def event_counts(self, *, window: str, tenant_id: str | None = None) -> EventCounts | None:
        """Events in the window and how many failed.

        Prefers HTTP status codes when the journal carries them and the window
        has any; falls back to dead-letter topic share, which every journal has.
        """
        columns = self.columns()
        time_column = self.time_column()
        if time_column is None:
            return None

        if "status_code" in columns:
            params: list[object] = []
            clause = _where(
                self._window_predicate(time_column, window),
                self._tenant_predicate(tenant_id, params),
            )
            sql = (
                # FILTER is rewritten to countIf on ClickHouse; no value here.
                "SELECT COUNT(*) FILTER (WHERE status_code IS NOT NULL) AS total, "  # nosec B608  # noqa: S608
                "COUNT(*) FILTER (WHERE status_code >= 500) AS errors "
                f"FROM {JOURNAL_TABLE}{clause}"
            )
            counts = self._counts(self._rows(sql, params))
            if counts is not None and counts.total > 0:
                return counts

        params = []
        clause = _where(
            self._window_predicate(time_column, window),
            self._tenant_predicate(tenant_id, params),
        )
        sql = (
            # Same: identifiers only, values bound or escaped by _value().
            "SELECT COUNT(*) AS total, "  # nosec B608  # noqa: S608
            "COUNT(*) FILTER (WHERE topic = 'events.deadletter') AS errors "
            f"FROM {JOURNAL_TABLE}{clause}"
        )
        return self._counts(self._rows(sql, params))

    @staticmethod
    def _counts(rows: list[dict]) -> EventCounts | None:
        if not rows:
            return None
        row = rows[0]
        total = row.get("total")
        if total is None:
            return None
        # ClickHouse's JSON transport quotes 64-bit integers; int() takes both.
        return EventCounts(total=int(total), errors=int(row.get("errors") or 0))
