import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_quality_validators_are_a_strict_mypy_slice() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_config = pyproject["tool"]["mypy"]
    overrides = mypy_config.get("overrides", [])

    strict_modules = {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is True
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }

    assert mypy_config["disallow_untyped_defs"] is False
    assert "src.quality.validators.*" in strict_modules


def _strict_modules() -> set[str]:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = pyproject["tool"]["mypy"].get("overrides", [])
    return {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is True
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }


def test_auth_package_is_a_strict_mypy_slice() -> None:
    # Auth is security-critical: every def in src/serving/api/auth must carry
    # full annotations so the key / rate-limit / audit paths stay type-checked.
    assert "src.serving.api.auth.*" in _strict_modules()


def test_quality_monitors_are_a_strict_mypy_slice() -> None:
    # Monitors gate freshness / SLA / pipeline-health signals; keep them fully
    # annotated so the observability path stays type-checked.
    assert "src.quality.monitors.*" in _strict_modules()


def test_semantic_layer_is_a_strict_mypy_slice() -> None:
    # Catalog / NL->SQL / contracts is the agent-facing query surface; keep it
    # fully annotated.
    assert "src.serving.semantic_layer.*" in _strict_modules()


def test_serving_backends_are_a_strict_mypy_slice() -> None:
    # Backends build / execute SQL (the H-C1 / H-C2 injection-hardening
    # surface); keep them fully annotated.
    assert "src.serving.backends.*" in _strict_modules()


def test_orchestration_dags_are_a_strict_mypy_slice() -> None:
    # Batch DAGs drive Iceberg maintenance + aggregate materialization; keep
    # the scheduled asset functions fully annotated.
    assert "src.orchestration.dags.*" in _strict_modules()


def test_event_replayer_is_a_strict_mypy_slice() -> None:
    # Dead-letter event replay re-emits failed events through the transactional
    # outbox; keep this delivery-correctness path fully annotated.
    assert "src.processing.event_replayer" in _strict_modules()


def test_local_pipeline_is_a_strict_mypy_slice() -> None:
    # The local end-to-end pipeline (generate->validate->enrich->DuckDB) is the
    # zero-infra demo path; keep it fully annotated.
    assert "src.processing.local_pipeline" in _strict_modules()


def test_outbox_is_a_strict_mypy_slice() -> None:
    # The transactional outbox is an at-least-once delivery-guarantee path;
    # keep it fully annotated.
    assert "src.processing.outbox" in _strict_modules()


def test_api_middleware_is_a_strict_mypy_slice() -> None:
    # Request middleware (correlation logging + HTTP metrics + tracing) is the
    # per-request observability path; keep it fully annotated.
    assert "src.serving.api.middleware.*" in _strict_modules()


def test_deadletter_router_is_a_strict_mypy_slice() -> None:
    # The dead-letter router is the operator-facing recovery surface over the
    # same table the event_replayer / outbox slices manage; keep it annotated.
    assert "src.serving.api.routers.deadletter" in _strict_modules()


def test_webhooks_router_is_a_strict_mypy_slice() -> None:
    # Webhooks expose tenant-scoped callback registration and delivery logs;
    # keep this operator integration surface fully annotated.
    assert "src.serving.api.routers.webhooks" in _strict_modules()


def test_alerts_router_is_a_strict_mypy_slice() -> None:
    # Alerts expose tenant-scoped rule management, test dispatch, and history;
    # keep this operator integration surface fully annotated.
    assert "src.serving.api.routers.alerts" in _strict_modules()


def test_contracts_router_is_a_strict_mypy_slice() -> None:
    # Contract routes are the schema governance API; keep version lookup,
    # diff, and validation endpoints fully annotated.
    assert "src.serving.api.routers.contracts" in _strict_modules()


def test_agent_query_router_is_a_strict_mypy_slice() -> None:
    # Agent query routes are the core LLM-facing API for query execution,
    # entity lookup, metrics, and catalog discovery; keep them annotated.
    assert "src.serving.api.routers.agent_query" in _strict_modules()
