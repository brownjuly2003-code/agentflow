import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow.cli import cli


class _DummyStreamResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(self._lines)


class _DummyHttpClient:
    def __init__(self, stream_lines: list[str] | None = None):
        self.stream_lines = stream_lines or []

    def stream(self, method: str, path: str, params=None):
        return _DummyStreamResponse(self.stream_lines)


class _DummyClient:
    def __init__(
        self,
        responses: dict[tuple[str, str], dict] | None = None,
        stream_lines: list[str] | None = None,
    ):
        self.responses = responses or {}
        self._client = _DummyHttpClient(stream_lines=stream_lines)

    def _request(self, method: str, path: str, params=None, json=None):
        return deepcopy(self.responses[(method, path)])


@pytest.fixture
def runner():
    return CliRunner()


def test_help_lists_available_commands(runner):
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "health" in result.output
    assert "entity" in result.output
    assert "stream" in result.output


def test_health_human_output_shows_components(monkeypatch, runner):
    payload = {
        "status": "healthy",
        "checked_at": "2026-04-10T14:23:01Z",
        "components": [
            {
                "name": "pipeline",
                "status": "healthy",
                "message": "freshness: 4.2s",
                "metrics": {"freshness_seconds": 4.2},
                "source": "live",
            },
            {
                "name": "kafka",
                "status": "healthy",
                "message": "lag: 0",
                "metrics": {"lag": 0},
                "source": "live",
            },
        ],
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/health"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["health"])

    assert result.exit_code == 0
    assert "pipeline" in result.output.lower()
    assert "kafka" in result.output.lower()
    assert "freshness: 4.2s" in result.output


def test_health_json_outputs_raw_payload(monkeypatch, runner):
    payload = {
        "status": "healthy",
        "checked_at": "2026-04-10T14:23:01Z",
        "components": [],
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/health"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["--json", "health"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload


def test_entity_order_formats_record(monkeypatch, runner):
    payload = {
        "entity_type": "order",
        "entity_id": "ORD-1",
        "data": {
            "order_id": "ORD-1",
            "status": "delivered",
            "total_amount": 249.99,
            "currency": "USD",
            "customer_id": "USR-42",
            "items_count": 3,
            "created_at": "2026-04-09T11:30:00Z",
        },
        "last_updated": "2026-04-10T14:23:01Z",
        "freshness_seconds": 3.1,
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/entity/order/ORD-1"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["entity", "order", "ORD-1"])

    assert result.exit_code == 0
    assert "Order ORD-1" in result.output
    assert "delivered" in result.output
    assert "249.99" in result.output
    assert "USR-42" in result.output


def test_metric_formats_value_with_window(monkeypatch, runner):
    payload = {
        "metric_name": "revenue",
        "value": 142847.0,
        "unit": "USD",
        "window": "24h",
        "computed_at": "2026-04-10T14:23:01Z",
        "components": {},
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/metrics/revenue"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["metric", "revenue", "--window", "24h"])

    assert result.exit_code == 0
    assert "revenue" in result.output.lower()
    assert "24h" in result.output
    assert "USD" in result.output


def test_search_human_output_shows_results_table(monkeypatch, runner):
    payload = {
        "query": "urgent order",
        "results": [
            {
                "type": "entity",
                "id": "ORD-1",
                "entity_type": "order",
                "score": 0.98,
                "snippet": "Delayed order",
                "endpoint": "/v1/entity/order/ORD-1",
            }
        ],
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/search"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["search", "urgent order"])

    assert result.exit_code == 0
    assert "ORD-1" in result.output
    assert "Delayed order" in result.output


def test_catalog_human_output_lists_entities_and_metrics(monkeypatch, runner):
    payload = {
        "entities": {
            "order": {
                "description": "Orders",
                "fields": {"order_id": "ID"},
                "primary_key": "order_id",
            }
        },
        "metrics": {
            "revenue": {
                "description": "Revenue",
                "unit": "USD",
                "available_windows": ["1h", "24h"],
            }
        },
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/catalog"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["catalog"])

    assert result.exit_code == 0
    assert "order" in result.output.lower()
    assert "revenue" in result.output.lower()


def test_slo_human_output_lists_statuses(monkeypatch, runner):
    payload = {
        "slos": [
            {
                "name": "freshness",
                "target": 0.99,
                "current": 1.0,
                "error_budget_remaining": 1.0,
                "status": "healthy",
                "window_days": 7,
            }
        ]
    }
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            {
                ("GET", "/v1/slo"): payload,
            }
        ),
    )

    result = runner.invoke(cli, ["slo"])

    assert result.exit_code == 0
    assert "freshness" in result.output.lower()
    assert "healthy" in result.output.lower()


def test_config_uses_env_and_masks_api_key(monkeypatch, runner):
    monkeypatch.setenv("AGENTFLOW_URL", "http://env-host:9000")
    monkeypatch.setenv("AGENTFLOW_API_KEY", "af-secret-key")
    monkeypatch.setattr("agentflow.cli.get_client", lambda url, key: _DummyClient())

    result = runner.invoke(cli, ["config"])

    assert result.exit_code == 0
    assert "http://env-host:9000" in result.output
    assert "af-secret-key" not in result.output
    assert "af*********ey" in result.output


def test_stream_prints_sse_events(monkeypatch, runner):
    monkeypatch.setattr(
        "agentflow.cli.get_client",
        lambda url, key: _DummyClient(
            stream_lines=[
                ": keepalive",
                'data: {"event_id":"evt-1","event_type":"order.created","entity_id":"ORD-1"}',
            ]
        ),
    )

    result = runner.invoke(cli, ["stream", "--type", "order"])

    assert result.exit_code == 0
    assert "evt-1" in result.output
    assert "order.created" in result.output
