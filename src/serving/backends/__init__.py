from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from src.serving.backends.duckdb_backend import DuckDBBackend


class BackendExecutionError(RuntimeError):
    """Raised when a backend query cannot be executed."""


class BackendMissingTableError(BackendExecutionError):
    """Raised when a backend query references a table that does not exist."""

    def __init__(self, message: str, table_name: str | None = None) -> None:
        super().__init__(message)
        self.table_name = table_name


class ServingBackend(ABC):
    name = "backend"

    @abstractmethod
    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute SQL and return rows as dictionaries."""

    @abstractmethod
    def scalar(self, sql: str, params: list | None = None) -> Any:
        """Execute SQL and return the first scalar value."""

    @abstractmethod
    def table_columns(self, table_name: str) -> set[str]:
        """Return the columns available in a table."""

    @abstractmethod
    def explain(self, sql: str) -> list[tuple]:
        """Explain a SQL statement."""

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create the serving tables. Idempotent DDL.

        Provisioning is a *writer* privilege. The API process never calls this
        on an external store: it would force the serving identity to hold
        CREATE/ALTER, and several booting replicas would race on it. External
        stores are provisioned out of band — ``python -m src.serving.provision``
        (or the bridge writer, which already holds write grants).
        """

    @abstractmethod
    def seed_demo_data(self) -> None:
        """Insert the canonical demo rows, and only if the store is empty.

        Demo data is not production data. This runs from the provisioning CLI or
        from an API booted with an explicit demo profile, never by default
        (audit P0-2).
        """

    def initialize_demo_data(self) -> None:
        """Provision and seed in one call — reference/demo convenience.

        Kept for the bridge writer and the provisioning CLI, which legitimately
        own both privileges. Prefer the two steps separately when the caller
        holds only one of them.
        """
        self.ensure_schema()
        self.seed_demo_data()

    @abstractmethod
    def health(self) -> dict:
        """Return a lightweight backend health payload."""


def default_serving_config_path() -> Path:
    return Path(os.getenv("AGENTFLOW_SERVING_CONFIG", "config/serving.yaml"))


def load_serving_backend_config(config_path: Path | str | None = None) -> dict:
    path = Path(config_path) if config_path is not None else default_serving_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(raw) or {}
        else:  # pragma: no cover
            data = json.loads(raw)

    clickhouse = data.get("clickhouse", {})
    backend_name = os.getenv("SERVING_BACKEND", data.get("backend", "duckdb"))

    return {
        "backend": str(backend_name).strip().lower() or "duckdb",
        "clickhouse": {
            "host": os.getenv("CLICKHOUSE_HOST", clickhouse.get("host", "localhost")),
            "port": int(os.getenv("CLICKHOUSE_PORT", clickhouse.get("port", 8123))),
            "user": os.getenv("CLICKHOUSE_USER", clickhouse.get("user", "default")),
            "password": os.getenv("CLICKHOUSE_PASSWORD", clickhouse.get("password", "")),
            "database": os.getenv("CLICKHOUSE_DATABASE", clickhouse.get("database", "agentflow")),
            "secure": (
                str(os.getenv("CLICKHOUSE_SECURE", clickhouse.get("secure", "false"))).lower()
                in {"1", "true", "yes", "on"}
            ),
            # Path to a PEM CA bundle for a private-CA ClickHouse endpoint
            # (audit P2-3). Only meaningful with secure=true; when set, it
            # replaces the system trust store for this connection.
            "ca_cert": os.getenv("CLICKHOUSE_CA_CERT", clickhouse.get("ca_cert", "")) or None,
            "timeout_seconds": int(
                os.getenv("CLICKHOUSE_TIMEOUT_SECONDS", clickhouse.get("timeout_seconds", 10))
            ),
        },
    }


def create_backend(
    *,
    duckdb_backend: DuckDBBackend,
    config_path: Path | str | None = None,
) -> ServingBackend:
    config = load_serving_backend_config(config_path)
    backend_name = config["backend"]

    if backend_name == "duckdb":
        return duckdb_backend
    if backend_name == "clickhouse":
        from src.serving.backends.clickhouse_backend import ClickHouseBackend

        clickhouse = config["clickhouse"]
        return ClickHouseBackend(
            host=clickhouse["host"],
            port=clickhouse["port"],
            user=clickhouse["user"],
            password=clickhouse["password"],
            database=clickhouse["database"],
            secure=clickhouse["secure"],
            timeout_seconds=clickhouse["timeout_seconds"],
            ca_cert=clickhouse["ca_cert"],
        )
    raise ValueError(f"Unsupported serving backend '{backend_name}'.")
