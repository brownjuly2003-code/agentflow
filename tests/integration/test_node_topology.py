"""Three-node demo topology — full-app node invariants (ADR 0012 / build §13).

N1/N2 here; later steps extend this file with N3-N5/N8/N12 as the ingest
endpoint, emitter, branch seed, and cross-branch view land. Every case boots
the real ``app`` via ``TestClient`` (in-memory DuckDB, no Docker).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app

pytestmark = pytest.mark.integration


def _boot(monkeypatch: pytest.MonkeyPatch, **env: str) -> Iterator[TestClient]:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def standalone_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # No AGENTFLOW_NODE_ROLE — today's single-node demo.
    monkeypatch.delenv("AGENTFLOW_NODE_ROLE", raising=False)
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    yield from _boot(monkeypatch)


def test_standalone_resolves_standalone_role(standalone_client: TestClient) -> None:
    # N1: unset role == standalone.
    assert standalone_client.app.state.node_role == "standalone"
    assert standalone_client.app.state.node_branch is None
    assert standalone_client.app.state.node_config.is_standalone


def test_standalone_does_not_register_ingest_route(standalone_client: TestClient) -> None:
    # N2: the ingest route is mounted only in center role, so it is absent from
    # a standalone node's routing table entirely (step 2 adds the center mount
    # and the full 404/200-by-role HTTP matrix).
    paths = {getattr(route, "path", None) for route in standalone_client.app.routes}
    assert "/v1/node/events" not in paths


def test_standalone_has_no_emitter_task(standalone_client: TestClient) -> None:
    # N1: no emitter task in standalone role.
    assert getattr(standalone_client.app.state, "node_emitter_task", None) is None


def test_standalone_health_still_serves(standalone_client: TestClient) -> None:
    # N1: the existing surface is byte-identical — health still 200.
    assert standalone_client.get("/v1/health").status_code == 200


def test_standalone_ingest_absent_from_public_schema(standalone_client: TestClient) -> None:
    # The node federation endpoint is internal (token-authed, center-only); it
    # must never appear in the public agent-facing OpenAPI catalog.
    schema = standalone_client.get("/openapi.json").json()
    assert "/v1/node/events" not in schema.get("paths", {})
