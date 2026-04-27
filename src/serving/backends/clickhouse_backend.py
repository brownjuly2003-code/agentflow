from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.serving.backends import BackendExecutionError, BackendMissingTableError, ServingBackend


class ClickHouseBackend(ServingBackend):
    name = "clickhouse"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        secure: bool = False,
        timeout_seconds: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._secure = secure
        self._timeout_seconds = timeout_seconds
        scheme = "https" if secure else "http"
        self._base_url = f"{scheme}://{host}:{port}"

    def _request(self, sql: str, *, expect_json: bool) -> str:
        translated_sql = self._translate_sql(sql)
        url = f"{self._base_url}/?database={quote(self._database)}"
        if expect_json:
            url = f"{url}&default_format=JSON"

        request = Request(url, data=translated_sql.encode("utf-8"), method="POST")
        if self._user or self._password:
            token = base64.b64encode(f"{self._user}:{self._password}".encode()).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                decoded: str = response.read().decode("utf-8")
                return decoded
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if "UNKNOWN_TABLE" in detail or "doesn't exist" in detail:
                table_match = re.search(r"table ([^\\s]+)", detail, flags=re.IGNORECASE)
                table_name = table_match.group(1) if table_match else None
                raise BackendMissingTableError(detail.strip(), table_name=table_name) from exc
            raise BackendExecutionError(detail.strip() or str(exc)) from exc
        except URLError as exc:
            raise BackendExecutionError(str(exc.reason)) from exc

    def _translate_sql(self, sql: str) -> str:
        translated = sql.replace("NOW()", "now()")
        translated = translated.replace(" FALSE", " 0").replace(" TRUE", " 1")
        translated = re.sub(
            r"COUNT\(\*\)\s+FILTER\s+\(WHERE\s+(.+?)\)",
            lambda match: f"countIf({match.group(1)})",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            r"countIf\((.+?)\)::FLOAT\b",
            lambda match: f"CAST(countIf({match.group(1)}) AS Float64)",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(r"::FLOAT\b", "", translated, flags=re.IGNORECASE)
        translated = re.sub(r"\bNULLIF\(", "nullIf(", translated, flags=re.IGNORECASE)
        translated = re.sub(r"\bCOUNT\(\*\)", "count()", translated, flags=re.IGNORECASE)
        translated = re.sub(
            r"CAST\((.+?)\s+AS\s+FLOAT\)",
            lambda match: f"CAST({match.group(1)} AS Float64)",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            r"CAST\((.+?)\s+AS\s+TIMESTAMP\)",
            lambda match: f"CAST({match.group(1)} AS DateTime)",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            r"INTERVAL\s+'(\d+)\s+(minute|minutes|hour|hours|day|days)'",
            lambda match: f"INTERVAL {match.group(1)} {match.group(2).rstrip('s').upper()}",
            translated,
            flags=re.IGNORECASE,
        )
        return translated

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        del params
        payload = self._request(sql, expect_json=True)
        data = json.loads(payload)
        rows: list[dict] = data.get("data", [])
        return rows

    def scalar(self, sql: str, params: list | None = None):
        del params
        rows = self.execute(sql)
        if not rows:
            return None
        return next(iter(rows[0].values()))

    def table_columns(self, table_name: str) -> set[str]:
        try:
            rows = self.execute(f"DESCRIBE TABLE {table_name}")
        except BackendMissingTableError:
            return set()
        except BackendExecutionError as exc:
            if "UNKNOWN_DATABASE" in str(exc):
                return set()
            raise
        return {str(row["name"]) for row in rows if "name" in row}

    def explain(self, sql: str) -> list[tuple]:
        raw = self._request(f"EXPLAIN {sql}", expect_json=False)
        return [(line,) for line in raw.splitlines() if line.strip()]

    def initialize_demo_data(self) -> None:
        self._request(f"CREATE DATABASE IF NOT EXISTS {self._database}", expect_json=False)
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.orders_v2 (
                order_id String,
                user_id String,
                status String,
                total_amount Decimal(10, 2),
                currency String,
                created_at DateTime
            ) ENGINE = MergeTree()
            ORDER BY order_id
        """,
            expect_json=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.products_current (
                product_id String,
                name String,
                category String,
                price Decimal(10, 2),
                in_stock UInt8,
                stock_quantity Int32
            ) ENGINE = MergeTree()
            ORDER BY product_id
        """,
            expect_json=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.sessions_aggregated (
                session_id String,
                user_id Nullable(String),
                started_at DateTime,
                ended_at Nullable(DateTime),
                duration_seconds Nullable(Float64),
                event_count Int32,
                unique_pages Int32,
                funnel_stage String,
                is_conversion UInt8
            ) ENGINE = MergeTree()
            ORDER BY session_id
        """,
            expect_json=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.users_enriched (
                user_id String,
                total_orders Int32,
                total_spent Decimal(10, 2),
                first_order_at DateTime,
                last_order_at DateTime,
                preferred_category String
            ) ENGINE = MergeTree()
            ORDER BY user_id
        """,
            expect_json=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.pipeline_events (
                event_id String,
                topic String,
                tenant_id String DEFAULT 'default',
                processed_at DateTime
            ) ENGINE = MergeTree()
            ORDER BY (tenant_id, topic, processed_at, event_id)
        """,
            expect_json=False,
        )
        self._request(
            f"""
            ALTER TABLE {self._database}.pipeline_events
            ADD COLUMN IF NOT EXISTS tenant_id String DEFAULT 'default'
            """,
            expect_json=False,
        )

        existing_rows = self.scalar(f"SELECT count() AS value FROM {self._database}.orders_v2")  # nosec B608 - database name comes from trusted backend config
        if existing_rows is not None and int(existing_rows) > 0:
            return

        now = datetime.now(UTC).replace(microsecond=0)

        def ts(delta: timedelta) -> str:
            return (now - delta).strftime("%Y-%m-%d %H:%M:%S")

        self._request(
            "\n".join(
                [
                    f"INSERT INTO {self._database}.products_current VALUES",  # nosec B608 - demo seed data uses trusted config and generated timestamps
                    "('PROD-001', 'Wireless Headphones', 'electronics', 79.99, 1, 142),",
                    "('PROD-002', 'Running Shoes', 'footwear', 129.99, 1, 58),",
                    "('PROD-003', 'Coffee Maker', 'kitchen', 49.99, 1, 203),",
                    "('PROD-004', 'Mechanical Keyboard', 'electronics', 149.99, 1, 37),",
                    "('PROD-005', 'Yoga Mat', 'fitness', 34.99, 1, 315),",
                    "('PROD-006', 'Backpack', 'accessories', 89.99, 1, 94),",
                    "('PROD-007', 'Water Bottle', 'fitness', 24.99, 1, 421),",
                    "('PROD-008', 'Desk Lamp', 'home', 44.99, 0, 0),",
                    "('PROD-009', 'Bluetooth Speaker', 'electronics', 59.99, 1, 167),",
                    "('PROD-010', 'Sunglasses', 'accessories', 119.99, 1, 72)",
                ]
            ),
            expect_json=False,
        )
        self._request(
            "\n".join(
                [
                    f"INSERT INTO {self._database}.orders_v2 VALUES",  # nosec B608 - demo seed data uses trusted config and generated timestamps
                    f"('ORD-20260404-1001', 'USR-10001', 'delivered', 159.98, 'USD', '{ts(timedelta(hours=2))}'),",
                    f"('ORD-20260404-1002', 'USR-10002', 'shipped', 129.99, 'USD', '{ts(timedelta(minutes=90))}'),",
                    f"('ORD-20260404-1003', 'USR-10001', 'confirmed', 249.97, 'USD', '{ts(timedelta(hours=1))}'),",
                    f"('ORD-20260404-1004', 'USR-10003', 'pending', 79.99, 'USD', '{ts(timedelta(minutes=45))}'),",
                    f"('ORD-20260404-1005', 'USR-10004', 'delivered', 89.99, 'USD', '{ts(timedelta(minutes=30))}'),",
                    f"('ORD-20260404-1006', 'USR-10002', 'cancelled', 34.99, 'USD', '{ts(timedelta(minutes=20))}'),",
                    f"('ORD-20260404-1007', 'USR-10005', 'confirmed', 179.98, 'USD', '{ts(timedelta(minutes=15))}'),",
                    f"('ORD-20260404-1008', 'USR-10003', 'pending', 59.99, 'USD', '{ts(timedelta(minutes=5))}')",
                ]
            ),
            expect_json=False,
        )
        self._request(
            "\n".join(
                [
                    f"INSERT INTO {self._database}.users_enriched VALUES",  # nosec B608 - demo seed data uses trusted config and generated timestamps
                    f"('USR-10001', 15, 2340.50, '{ts(timedelta(days=180))}', '{ts(timedelta(hours=1))}', 'electronics'),",
                    f"('USR-10002', 8, 890.20, '{ts(timedelta(days=90))}', '{ts(timedelta(minutes=20))}', 'footwear'),",
                    f"('USR-10003', 3, 210.00, '{ts(timedelta(days=30))}', '{ts(timedelta(minutes=5))}', 'electronics'),",
                    f"('USR-10004', 22, 4100.75, '{ts(timedelta(days=365))}', '{ts(timedelta(minutes=30))}', 'accessories'),",
                    f"('USR-10005', 1, 179.98, '{ts(timedelta(days=1))}', '{ts(timedelta(minutes=15))}', 'electronics')",
                ]
            ),
            expect_json=False,
        )
        self._request(
            "\n".join(
                [
                    f"INSERT INTO {self._database}.sessions_aggregated VALUES",  # nosec B608 - demo seed data uses trusted config and generated timestamps
                    f"('SES-a1b2c3', 'USR-10001', '{ts(timedelta(hours=2))}', '{ts(timedelta(minutes=100))}', 1200, 14, 6, 'checkout', 1),",
                    f"('SES-d4e5f6', 'USR-10002', '{ts(timedelta(minutes=90))}', '{ts(timedelta(minutes=70))}', 1200, 8, 4, 'add_to_cart', 0),",
                    f"('SES-g7h8i9', NULL, '{ts(timedelta(minutes=60))}', '{ts(timedelta(minutes=58))}', 120, 2, 2, 'bounce', 0),",
                    f"('SES-j1k2l3', 'USR-10003', '{ts(timedelta(minutes=45))}', '{ts(timedelta(minutes=20))}', 1500, 11, 5, 'checkout', 1),",
                    f"('SES-m4n5o6', 'USR-10004', '{ts(timedelta(minutes=30))}', '{ts(timedelta(minutes=15))}', 900, 6, 3, 'product_view', 0),",
                    f"('SES-p7q8r9', 'USR-10005', '{ts(timedelta(minutes=20))}', NULL, NULL, 3, 2, 'browse', 0)",
                ]
            ),
            expect_json=False,
        )
        self._request(
            "\n".join(
                [
                    f"INSERT INTO {self._database}.pipeline_events (event_id, topic, tenant_id, processed_at) VALUES",  # nosec B608 - demo seed data uses trusted config and generated timestamps
                    f"('evt-001', 'events.validated', 'default', '{ts(timedelta(minutes=10))}'),",
                    f"('evt-002', 'events.validated', 'default', '{ts(timedelta(minutes=9))}'),",
                    f"('evt-003', 'events.validated', 'default', '{ts(timedelta(minutes=8))}'),",
                    f"('evt-004', 'events.deadletter', 'default', '{ts(timedelta(minutes=7))}'),",
                    f"('evt-005', 'events.validated', 'default', '{ts(timedelta(minutes=6))}'),",
                    f"('evt-006', 'events.validated', 'default', '{ts(timedelta(minutes=5))}'),",
                    f"('evt-007', 'events.validated', 'default', '{ts(timedelta(minutes=4))}'),",
                    f"('evt-008', 'events.validated', 'default', '{ts(timedelta(minutes=3))}'),",
                    f"('evt-009', 'events.deadletter', 'default', '{ts(timedelta(minutes=2))}'),",
                    f"('evt-010', 'events.validated', 'default', '{ts(timedelta(minutes=1))}')",
                ]
            ),
            expect_json=False,
        )

    def health(self) -> dict:
        try:
            value = self.scalar("SELECT 1 AS value")
        except BackendExecutionError as exc:
            return {"backend": self.name, "status": "error", "error": str(exc)}
        return {
            "backend": self.name,
            "status": "ok" if value == 1 else "error",
            "host": self._host,
            "port": self._port,
            "database": self._database,
        }
