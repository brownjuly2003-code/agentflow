from __future__ import annotations

from scripts.export_openapi import _normalize_fastapi_validation_error_schema


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

    normalized = _normalize_fastapi_validation_error_schema(schema)

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
