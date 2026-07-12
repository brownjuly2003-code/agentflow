"""Every public read goes through the active serving backend (audit P0-3).

`/v1/lineage`, `/v1/slo`, `/v1/search` and the health collector each reached
past the configured backend and read the embedded DuckDB directly. On the
ClickHouse profile the API therefore answered half its surface from a store
nobody was writing to: entity and metric came from ClickHouse while lineage
reconstructed provenance, SLO computed an error budget, and health reported
freshness — all from demo rows. That is worse than an outage, because it looks
like an answer.

Two halves are pinned here. A static ratchet: no read surface may reach for a
private connection. And a behavioural proof: point the engine at a backend
holding data that does not exist in DuckDB, and every read surface must return
*that* data.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.quality.monitors.metrics_collector import CheckSource, HealthCollector, HealthStatus
from src.serving.api.routers.lineage import router as lineage_router
from src.serving.api.routers.slo import router as slo_router
from src.serving.backends import ServingBackend
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.journal import JournalReader
from src.serving.semantic_layer.search_index import SearchIndex

ROOT = Path(__file__).resolve().parents[2]

# The attributes that bypassed the configured backend.
_PRIVATE_ATTRS = {"_conn", "_backend", "_duckdb_backend"}
_ENGINE_NAMES = {"query_engine", "engine", "worker_engine"}


def _reaches_into_the_engine(source: str) -> bool:
    """True if the module reads an engine's private parts *in code*.

    Parsed, not grepped: `control_plane/__init__.py` documents the rule in prose
    ("never through ``query_engine._conn``"), and a text match would flag the
    warning as the violation.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Attribute) or node.attr not in _PRIVATE_ATTRS:
            continue
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr in _ENGINE_NAMES:
            return True  # app.state.query_engine._conn
        if isinstance(owner, ast.Name) and owner.id in _ENGINE_NAMES:
            return True  # engine._conn
    return False


# Files allowed to hold the engine's private parts, each for a reason that is
# not "a read surface taking a shortcut".
_COMPOSITION_ROOTS = {
    # Builds the engine, and hands the embedded connection to the control-plane
    # store and the demo/node seeders.
    "src/serving/api/main.py",
    # Owns them.
    "src/serving/semantic_layer/query/engine.py",
    # Resolves the embedded connection per call through a provider lambda.
    "src/serving/control_plane/store.py",
    # Write paths on the embedded store, deliberately out of P0-3's scope (which
    # is about *reads* answering from the wrong store): the batch worker clones
    # the engine and needs its own DuckDB cursor, and node-federation ingest
    # appends to the embedded journal.
    "src/serving/api/routers/batch.py",
    "src/serving/node/ingest.py",
}


def test_no_read_surface_reaches_past_the_backend() -> None:
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.joinpath("src").rglob("*.py")
        if _reaches_into_the_engine(path.read_text(encoding="utf-8"))
    )

    unexpected = [path for path in offenders if path not in _COMPOSITION_ROOTS]
    assert not unexpected, (
        f"{unexpected} reach into the query engine's private connection. A read "
        "surface must go through `query_engine.backend` or "
        "`query_engine.journal`, or it will answer from the embedded DuckDB "
        "whatever SERVING_BACKEND says (audit P0-3)."
    )


class _RecordingBackend(ServingBackend):
    """A serving backend that is demonstrably not DuckDB.

    Answers the journal reads with one row that exists nowhere else, and records
    every statement it is handed.
    """

    name = "recording"

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.statements: list[str] = []
        self._rows = rows if rows is not None else []
        self.reachable = True

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        del params
        self.statements.append(sql)
        return list(self._rows)

    def scalar(self, sql: str, params: list | None = None) -> Any:
        rows = self.execute(sql, params)
        return next(iter(rows[0].values())) if rows else None

    def table_columns(self, table_name: str) -> set[str]:
        if table_name == "pipeline_events":
            return {
                "event_id",
                "topic",
                "tenant_id",
                "entity_id",
                "event_type",
                "latency_ms",
                "processed_at",
            }
        return {"order_id", "user_id", "status", "total_amount", "currency", "created_at"}

    def explain(self, sql: str) -> list[tuple]:
        return []

    def ensure_schema(self) -> None:
        return None

    def seed_demo_data(self) -> None:
        return None

    def health(self) -> dict:
        if not self.reachable:
            return {"backend": self.name, "status": "error", "error": "connection refused"}
        return {"backend": self.name, "status": "ok"}


class _EngineStub:
    """The engine's public read surface, and nothing else."""

    def __init__(self, backend: _RecordingBackend) -> None:
        self.backend = backend
        self.journal = JournalReader(backend)
        self.catalog = DataCatalog()
        self.scanned: list[str] = []

    def scan_entity_rows(self, table_name: str, *, limit: int) -> list[dict]:
        self.scanned.append(table_name)
        return self.backend.execute(f"SELECT * FROM {table_name} LIMIT {limit}")

    def get_metric(self, name: str, window: str = "24h") -> dict:
        return {"value": 42.0, "unit": "RUB"}


def _journal_row() -> dict:
    # An id no DuckDB fixture in this repo ever seeds.
    return {
        "event_id": "evt-from-the-active-backend",
        "topic": "events.validated",
        "processed_at": "2026-07-11 10:00:00",
        "tenant_id": "default",
        "event_type": "order.validated",
        "entity_id": "ORD-ONLY-IN-BACKEND",
        "latency_ms": 12,
    }


@pytest.fixture
def backend() -> _RecordingBackend:
    return _RecordingBackend(rows=[_journal_row()])


@pytest.fixture
def client(backend: _RecordingBackend) -> TestClient:
    app = FastAPI()
    app.include_router(lineage_router)
    app.include_router(slo_router)
    app.state.query_engine = _EngineStub(backend)
    app.state.catalog = DataCatalog()
    return TestClient(app)


class TestLineage:
    def test_reads_the_active_backend(self, client: TestClient, backend: _RecordingBackend) -> None:
        response = client.get("/v1/lineage/order/ORD-ONLY-IN-BACKEND")

        assert response.status_code == 200
        assert any("pipeline_events" in statement for statement in backend.statements)

    def test_reports_the_store_that_served_it(
        self,
        client: TestClient,
        backend: _RecordingBackend,
    ) -> None:
        # The enrichment layer was hardcoded to system="duckdb", so a ClickHouse
        # deployment was told its data came from DuckDB.
        response = client.get("/v1/lineage/order/ORD-ONLY-IN-BACKEND")

        systems = {node["system"] for node in response.json()["lineage"]}
        assert "recording" in systems
        assert "duckdb" not in systems


class TestSlo:
    def test_reads_the_active_backend(self, client: TestClient, backend: _RecordingBackend) -> None:
        response = client.get("/v1/slo")

        assert response.status_code == 200
        assert response.json()["slos"]
        assert any("pipeline_events" in statement for statement in backend.statements)


class TestHealth:
    def test_freshness_and_quality_read_the_active_backend(
        self,
        backend: _RecordingBackend,
    ) -> None:
        collector = HealthCollector(journal=JournalReader(backend))

        components = {c.name: c for c in collector.collect().components}

        assert components["serving"].status is HealthStatus.HEALTHY
        assert components["serving"].metrics["backend"] == "recording"
        assert any("pipeline_events" in statement for statement in backend.statements)

    def test_a_dead_serving_store_is_not_healthy(self, backend: _RecordingBackend) -> None:
        backend.reachable = False
        collector = HealthCollector(journal=JournalReader(backend))

        components = {c.name: c for c in collector.collect().components}

        assert components["serving"].status is HealthStatus.UNHEALTHY

    def test_an_unwired_collector_says_so_instead_of_opening_its_own_store(self) -> None:
        # It used to duckdb.connect(DUCKDB_PATH) — on the ClickHouse profile an
        # unrelated database, and on the :memory: default a brand-new empty one.
        collector = HealthCollector()

        components = {c.name: c for c in collector.collect().components}

        assert components["freshness"].source is CheckSource.PLACEHOLDER
        assert components["quality"].source is CheckSource.PLACEHOLDER


class TestSearchIndex:
    def test_scans_the_active_backend(self, backend: _RecordingBackend) -> None:
        engine = _EngineStub(backend)
        index = SearchIndex(catalog=engine.catalog, query_engine=engine)  # type: ignore[arg-type]

        index.rebuild()

        assert engine.scanned, "the index must read entity tables through the backend"
        assert any("LIMIT" in statement for statement in backend.statements), (
            "the entity scan must be bounded — it materializes every row it reads"
        )
