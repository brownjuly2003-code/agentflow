import json
import warnings
from pathlib import Path

import httpx
import pytest
from hypothesis.errors import HypothesisWarning, NonInteractiveExampleWarning

pytest_plugins = ("tests.e2e.conftest",)

schemathesis = pytest.importorskip("schemathesis")

pytestmark = pytest.mark.integration

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
SCHEMA = schemathesis.openapi.from_path(OPENAPI_PATH)

warnings.filterwarnings("ignore", category=HypothesisWarning)
warnings.filterwarnings("ignore", category=NonInteractiveExampleWarning)


def _normalize_openapi_schemas(schemas: dict[str, object]) -> dict[str, object]:
    normalized = json.loads(json.dumps(schemas))
    validation_error = normalized.get("ValidationError")
    if isinstance(validation_error, dict):
        properties = validation_error.get("properties")
        if isinstance(properties, dict):
            properties.pop("input", None)
            properties.pop("ctx", None)
    return normalized


SUPPORTED_PATHS = {
    "/v1/query",
    "/v1/query/explain",
    "/v1/entity/{entity_type}/{entity_id}",
    "/v1/metrics/{metric_name}",
    "/v1/stream/events",
    "/v1/catalog",
    "/v1/health",
}


def _prepare_case(case) -> None:
    path = case.operation.path
    if path == "/v1/query":
        case.query = {}
        case.body = {"question": "Show me top 3 products", "limit": 3}
        return
    if path == "/v1/query/explain":
        case.query = {}
        case.body = {"question": "Top 5 products by revenue today"}
        return
    if path == "/v1/entity/{entity_type}/{entity_id}":
        case.path_parameters = {
            "entity_type": "order",
            "entity_id": "ORD-20260404-1001",
        }
        case.query = {}
        return
    if path == "/v1/metrics/{metric_name}":
        case.path_parameters = {"metric_name": "revenue"}
        case.query = {"window": "24h"}
        return
    if path == "/v1/stream/events":
        case.query = {}
        return
    if path in {"/v1/catalog", "/v1/health"}:
        case.query = {}
        return
    raise AssertionError(f"Unsupported documented path: {path}")


def test_api_follows_openapi_contract(base_url: str, ops_api_key: str):
    headers = {"X-API-Key": ops_api_key}

    for result in SCHEMA.get_all_operations():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NonInteractiveExampleWarning)
            case = result.ok().as_strategy().example()
        if case.operation.path not in SUPPORTED_PATHS:
            continue
        _prepare_case(case)

        if case.operation.path == "/v1/stream/events":
            with httpx.stream(
                "GET",
                f"{base_url}{case.operation.path}",
                headers=headers,
                params=case.query,
                timeout=10.0,
            ) as response:
                assert response.status_code != 500
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert any(
                    line.startswith("data: ")
                    for line in response.iter_lines()
                    if line and not line.startswith(":")
                )
            continue

        response = case.call(
            base_url=base_url,
            headers=headers,
            timeout=30 if case.operation.path == "/v1/health" else 10,
        )
        assert response.status_code != 500, (
            f"Server error on {case.operation.label}: {response.text}"
        )
        case.validate_response(response)


def test_documented_openapi_snapshot_matches_live_api(base_url: str):
    documented = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    live = httpx.get(f"{base_url}/openapi.json", timeout=10.0).json()

    documented_paths = documented.get("paths", {})
    live_paths = live.get("paths", {})
    assert {path: live_paths.get(path) for path in documented_paths} == documented_paths

    documented_schemas = documented.get("components", {}).get("schemas", {})
    live_schemas = live.get("components", {}).get("schemas", {})
    assert _normalize_openapi_schemas(
        {name: live_schemas.get(name) for name in documented_schemas}
    ) == _normalize_openapi_schemas(documented_schemas)
