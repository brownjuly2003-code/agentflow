"""Export OpenAPI schema and agent tool definitions.

By default writes to docs/openapi.json + docs/agent-tools/*.json.

With ``--check``, exits non-zero if the regenerated artifacts diverge from
what is committed (drift gate). Use this in CI to block PRs that change
HTTP routes / schemas without regenerating the contract files.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _resolve_refs(node: object, components: dict[str, object]) -> object:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            schema_name = ref.rsplit("/", 1)[-1]
            resolved = _resolve_refs(components[schema_name], components)
            extras = {
                key: _resolve_refs(value, components)
                for key, value in node.items()
                if key != "$ref"
            }
            if extras and isinstance(resolved, dict):
                return {**resolved, **extras}
            return resolved
        return {key: _resolve_refs(value, components) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(item, components) for item in node]
    return node


def _build_description(operation: dict[str, object]) -> str:
    parts = [
        str(operation.get("summary", "")).strip(),
        str(operation.get("description", "")).strip(),
    ]
    return "\n\n".join(part for part in parts if part)


def _build_input_schema(
    operation: dict[str, object],
    components: dict[str, object],
) -> dict[str, object]:
    properties: dict[str, object] = {}
    required: list[str] = []

    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        name = parameter["name"]
        schema = _resolve_refs(parameter.get("schema", {}), components)
        if (
            isinstance(schema, dict)
            and "description" not in schema
            and parameter.get("description")
        ):
            schema = {**schema, "description": parameter["description"]}
        properties[name] = schema
        if parameter.get("required"):
            required.append(name)

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        media_types = request_body.get("content", {})
        body_schema: object = {}
        if isinstance(media_types, dict) and media_types:
            if "application/json" in media_types:
                body_schema = media_types["application/json"].get("schema", {})
            else:
                body_schema = next(iter(media_types.values())).get("schema", {})
        body_schema = _resolve_refs(body_schema, components)

        if isinstance(body_schema, dict) and (
            body_schema.get("type") == "object" or "properties" in body_schema
        ):
            for name, schema in body_schema.get("properties", {}).items():
                properties[name] = schema
            required.extend(body_schema.get("required", []))
        elif body_schema:
            properties["body"] = body_schema
            if request_body.get("required"):
                required.append("body")

    input_schema: dict[str, object] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = list(dict.fromkeys(required))
    return input_schema


def _build_claude_tools(schema: dict[str, object]) -> list[dict[str, object]]:
    components = schema.get("components", {}).get("schemas", {})
    tools = []
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post"} or not isinstance(operation, dict):
                continue
            tools.append(
                {
                    "name": operation["operationId"],
                    "description": _build_description(operation),
                    "input_schema": _build_input_schema(operation, components),
                }
            )
    return tools


def _build_openai_tools(schema: dict[str, object]) -> list[dict[str, object]]:
    components = schema.get("components", {}).get("schemas", {})
    tools = []
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post"} or not isinstance(operation, dict):
                continue
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": operation["operationId"],
                        "description": _build_description(operation),
                        "parameters": _build_input_schema(operation, components),
                    },
                }
            )
    return tools


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _read_committed(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _serialize_json(payload: object) -> str:
    return json.dumps(payload, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if regenerated OpenAPI / agent tool files diverge from committed copies.",
    )
    args = parser.parse_args()

    from src.serving.api.main import app

    schema = app.openapi()
    docs_dir = ROOT / "docs"
    agent_tools_dir = docs_dir / "agent-tools"

    artifacts: list[tuple[Path, object]] = [
        (docs_dir / "openapi.json", schema),
        (agent_tools_dir / "claude-tools.json", _build_claude_tools(schema)),
        (agent_tools_dir / "openai-tools.json", _build_openai_tools(schema)),
    ]

    if args.check:
        drift: list[str] = []
        for target, payload in artifacts:
            current = _read_committed(target) or ""
            expected = _serialize_json(payload)
            if current != expected:
                drift.append(str(target.relative_to(ROOT)))
        if drift:
            sys.stderr.write(
                "OpenAPI / agent tool drift detected. Regenerate with "
                "`python scripts/export_openapi.py` and commit:\n"
            )
            for path in drift:
                sys.stderr.write(f"  - {path}\n")
            return 1
        return 0

    for target, payload in artifacts:
        _write_json(target, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
