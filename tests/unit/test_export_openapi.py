from __future__ import annotations

from pathlib import Path

from scripts import export_openapi

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_GENERATED_ARTIFACTS = (
    "docs/openapi.json",
    "docs/agent-tools/claude-tools.json",
    "docs/agent-tools/openai-tools.json",
)


def test_normalizes_fastapi_validation_error_schema_variants() -> None:
    schema = {
        "components": {
            "schemas": {
                "ValidationError": {
                    "properties": {
                        "loc": {"title": "Location"},
                        "msg": {"title": "Message"},
                        "type": {"title": "Error Type"},
                        "input": {"title": "Input"},
                        "ctx": {"title": "Context", "type": "object"},
                    },
                    "required": ["loc", "msg", "type", "input", "ctx"],
                    "title": "ValidationError",
                    "type": "object",
                }
            }
        }
    }

    normalized = export_openapi._normalize_fastapi_validation_error_schema(schema)

    properties = normalized["components"]["schemas"]["ValidationError"]["properties"]
    assert properties == {
        "loc": {"title": "Location"},
        "msg": {"title": "Message"},
        "type": {"title": "Error Type"},
    }
    assert normalized["components"]["schemas"]["ValidationError"]["required"] == [
        "loc",
        "msg",
        "type",
    ]
    assert "input" in schema["components"]["schemas"]["ValidationError"]["properties"]
    assert "ctx" in schema["components"]["schemas"]["ValidationError"]["properties"]


def test_generated_artifact_inventory_matches_the_exporter_outputs() -> None:
    schema: dict[str, object] = {"components": {"schemas": {}}, "paths": {}}

    assert (
        tuple(path.as_posix() for path in export_openapi.GENERATED_ARTIFACT_PATHS)
        == EXPECTED_GENERATED_ARTIFACTS
    )
    artifacts = export_openapi._build_artifacts(schema)
    assert tuple(path.relative_to(ROOT).as_posix() for path, _payload in artifacts) == (
        EXPECTED_GENERATED_ARTIFACTS
    )
    assert artifacts[0][1] is schema
    assert artifacts[1][1] == []
    assert artifacts[2][1] == []
    for relative in EXPECTED_GENERATED_ARTIFACTS:
        assert (ROOT / relative).is_file(), f"generated artifact is missing: {relative}"


def test_openapi_generated_reference_docs_name_owner_commands_and_lifecycle() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "## Generated-reference ownership" in docs_hub
    for relative in EXPECTED_GENERATED_ARTIFACTS:
        assert f"`{relative}`" in docs_hub
    assert "`python scripts/export_openapi.py`" in docs_hub
    assert "`python scripts/export_openapi.py --check`" in docs_hub
    assert "Do not hand-edit or update only part of the family" in docs_hub
    assert (
        "Historical OpenAPI comparison captures `docs/perf/live_openapi_local.json` and "
        "`docs/perf/live_openapi_ci.json` are evidence, not current generated references"
        in docs_hub
    )
    assert "[`sdk-capabilities.md`](sdk-capabilities.md)" in docs_hub
    assert "[`quality.md`](quality.md)" in docs_hub
    assert "[full-load benchmark lifecycle](perf/load-benchmark-latest.md)" in docs_hub
    assert "python scripts/export_openapi.py" in contributing
    assert "python scripts/export_openapi.py --check" in contributing
    assert "all three outputs" in contributing
    assert "OpenAPI generated-reference owner/drift sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_contract_workflow_checks_the_whole_openapi_generated_family() -> None:
    workflow = (ROOT / ".github" / "workflows" / "contract.yml").read_text(encoding="utf-8")

    assert "python scripts/export_openapi.py --check" in workflow
    assert '"docs/openapi.json"' in workflow
    assert '"docs/agent-tools/**"' in workflow
