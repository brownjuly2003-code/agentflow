from __future__ import annotations

import re
from datetime import UTC, datetime

from src.serving.backends import BackendExecutionError, BackendMissingTableError

from .contracts import QueryExecutionHost

WINDOW_MAP = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "6h": "6 hours",
    "24h": "24 hours",
    "now": "30 minutes",
}


class MetricQueryMixin:
    def get_metric(
        self: QueryExecutionHost,
        metric_name: str,
        window: str = "1h",
        as_of: datetime | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """Compute a metric value for the given time window.

        Raises ValueError if the backing table doesn't exist.
        Returns value=0 only when the query succeeds but yields no data.
        """
        metric_def = self.catalog.metrics.get(metric_name)
        if not metric_def:
            return {"value": 0, "unit": "unknown"}

        sql_interval = WINDOW_MAP.get(window, "1 hour")
        sql = self._scope_sql(metric_def.sql_template.format(window=sql_interval), tenant_id)
        local_tz = datetime.now().astimezone().tzinfo or UTC
        use_query_params = self._backend_name == self._duckdb_backend.name
        params: list[datetime] | None = None
        if as_of is not None:
            anchor_occurrences = sql.count("NOW()")
            anchor = as_of.astimezone(local_tz).replace(tzinfo=None)
            if use_query_params:
                sql = sql.replace("NOW()", "CAST(? AS TIMESTAMP)", anchor_occurrences)
                params = [anchor] * anchor_occurrences
            else:
                anchor_literal = self._quote_literal(anchor)
                sql = sql.replace(
                    "NOW()", f"CAST({anchor_literal} AS TIMESTAMP)", anchor_occurrences
                )
            time_match = re.search(
                r"(\w+)\s*>=\s*CAST\([^)]*\s+AS\s+TIMESTAMP\)",
                sql,
            )
            if time_match and " OR " not in sql.upper():
                if use_query_params:
                    sql = f"{sql} AND {time_match.group(1)} <= CAST(? AS TIMESTAMP)"
                    params = (params or []) + [anchor]
                else:
                    sql = f"{sql} AND {time_match.group(1)} <= CAST({anchor_literal} AS TIMESTAMP)"

        try:
            result = (
                self._backend.scalar(sql, params)
                if params is not None
                else self._backend.scalar(sql)
            )
            value = float(result) if result is not None else 0.0
        except BackendMissingTableError as e:
            table_match = re.search(r"Table.*?(\w+).*?not found", str(e))
            table_name = e.table_name or (table_match.group(1) if table_match else "unknown")
            raise ValueError(
                f"Metric '{metric_name}' depends on table '{table_name}' "
                f"which is not materialized yet"
            ) from e
        except BackendExecutionError as e:
            raise ValueError(f"Metric query failed: {e}") from e

        return {
            "value": round(value, 4),
            "unit": metric_def.unit,
        }
