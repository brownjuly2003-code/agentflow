"""AgentFlow MCP server.

Exposes AgentFlow as a set of Model Context Protocol tools so Claude
Desktop, Cursor, Windsurf, and any other MCP-aware client can fetch
live business state through a stdio transport.

Transport selection, auth, and timeouts are configured through
environment variables so a user can wire the server into a client
config without editing code:

- ``AGENTFLOW_API_URL``  — base URL of the AgentFlow API. Default
  ``http://localhost:8000``.
- ``AGENTFLOW_API_KEY``  — value passed as ``X-API-Key``. Empty string
  is treated as unauthenticated.
- ``AGENTFLOW_TIMEOUT_SECONDS`` — request timeout; default 10.

The tool handlers dispatch to :class:`agentflow.AgentFlowClient` and do
not duplicate HTTP logic.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from agentflow import AgentFlowClient
from agentflow.exceptions import (
    AgentFlowError,
    AuthError,
    DataFreshnessError,
    EntityNotFoundError,
    RateLimitError,
)
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

SERVER_NAME = "agentflow"

_ENTITY_TYPE_SCHEMA = {
    "type": "string",
    "description": (
        "Entity type registered in the catalog. Built-in types are 'order', "
        "'user', 'product', and 'session'."
    ),
}


AGENTFLOW_TOOLS: list[types.Tool] = [
    types.Tool(
        name="entity_lookup",
        description=(
            "Fetch the latest state of a single entity by type and id from the "
            "AgentFlow serving layer. Returns the full entity JSON or an error "
            "if the entity does not exist."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entity_type": _ENTITY_TYPE_SCHEMA,
                "entity_id": {
                    "type": "string",
                    "description": "Identifier of the entity, e.g. 'ORD-20260401-7829'.",
                },
            },
            "required": ["entity_type", "entity_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="metric_query",
        description=(
            "Fetch a business metric (revenue, order_count, avg_order_value, "
            "conversion_rate, active_sessions, error_rate) over a time window "
            "such as '1h', '24h', or '7d'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Metric name."},
                "window": {
                    "type": "string",
                    "description": "Time window string (1h, 24h, 7d).",
                    "default": "1h",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="nl_query",
        description=(
            "Ask a natural-language question about business data. AgentFlow "
            "plans and executes a read-only SQL query and returns the rows."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Plain English question.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Optional row limit.",
                    "minimum": 1,
                    "maximum": 10000,
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="health_check",
        description=(
            "Return the AgentFlow pipeline health summary including component "
            "statuses and freshness."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="list_entities",
        description=(
            "List the entity types, metrics, and query capabilities advertised "
            "by the AgentFlow catalog."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
]


_ENTITY_METHOD_BY_TYPE: dict[str, str] = {
    "order": "get_order",
    "user": "get_user",
    "product": "get_product",
    "session": "get_session",
}


def _default_client_factory() -> AgentFlowClient:
    base_url = os.environ.get("AGENTFLOW_API_URL", "http://localhost:8000")
    api_key = os.environ.get("AGENTFLOW_API_KEY", "")
    timeout_raw = os.environ.get("AGENTFLOW_TIMEOUT_SECONDS", "10")
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ValueError(
            f"AGENTFLOW_TIMEOUT_SECONDS must be a number, got {timeout_raw!r}."
        ) from exc
    return AgentFlowClient(base_url=base_url, api_key=api_key, timeout=timeout)


def _as_text(payload: Any) -> list[types.TextContent]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    return [types.TextContent(type="text", text=text)]


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _entity_lookup(client: AgentFlowClient, arguments: dict[str, Any]) -> Any:
    entity_type = str(arguments["entity_type"]).lower()
    entity_id = str(arguments["entity_id"])
    method_name = _ENTITY_METHOD_BY_TYPE.get(entity_type)
    if method_name is None:
        raise ValueError(
            f"Unsupported entity_type {entity_type!r}. "
            f"Known types: {sorted(_ENTITY_METHOD_BY_TYPE)}."
        )
    method: Callable[[str], Any] = getattr(client, method_name)
    return _dump(method(entity_id))


def _metric_query(client: AgentFlowClient, arguments: dict[str, Any]) -> Any:
    name = str(arguments["name"])
    window = str(arguments.get("window", "1h"))
    return _dump(client.get_metric(name, window))


def _nl_query(client: AgentFlowClient, arguments: dict[str, Any]) -> Any:
    question = str(arguments["question"])
    limit_raw = arguments.get("limit")
    limit = int(limit_raw) if limit_raw is not None else None
    return _dump(client.query(question, limit=limit))


def _health_check(client: AgentFlowClient, _: dict[str, Any]) -> Any:
    return _dump(client.health())


def _list_entities(client: AgentFlowClient, _: dict[str, Any]) -> Any:
    return _dump(client.catalog())


_TOOL_HANDLERS: dict[str, Callable[[AgentFlowClient, dict[str, Any]], Any]] = {
    "entity_lookup": _entity_lookup,
    "metric_query": _metric_query,
    "nl_query": _nl_query,
    "health_check": _health_check,
    "list_entities": _list_entities,
}


def handle_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    client: AgentFlowClient,
) -> list[types.TextContent]:
    """Dispatch a tool invocation and wrap the result as MCP content blocks.

    Exceptions are converted to a structured error payload rather than
    re-raised so MCP clients see an informative message.
    """
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _as_text({"error": f"Unknown tool {name!r}"})

    payload = arguments or {}
    try:
        result = handler(client, payload)
    except EntityNotFoundError as exc:
        return _as_text({"error": "not_found", "message": str(exc)})
    except AuthError as exc:
        return _as_text({"error": "auth", "message": str(exc)})
    except RateLimitError as exc:
        return _as_text({"error": "rate_limit", "message": str(exc)})
    except DataFreshnessError as exc:
        return _as_text({"error": "stale_data", "message": str(exc)})
    except AgentFlowError as exc:
        return _as_text({"error": "agentflow", "message": str(exc)})
    except ValueError as exc:
        return _as_text({"error": "invalid_argument", "message": str(exc)})
    return _as_text(result)


def build_server(
    client_factory: Callable[[], AgentFlowClient] | None = None,
) -> Server:
    """Create a configured :class:`mcp.server.Server` instance.

    A factory is used (rather than a ready client) so a fresh connection
    is opened lazily on first tool invocation, which keeps ``python -m
    agentflow_integrations.mcp`` cheap when the subprocess is started
    eagerly by Claude Desktop.
    """
    factory = client_factory or _default_client_factory
    client_holder: dict[str, AgentFlowClient] = {}

    def _client() -> AgentFlowClient:
        if "client" not in client_holder:
            client_holder["client"] = factory()
        return client_holder["client"]

    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list(AGENTFLOW_TOOLS)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        return handle_tool_call(name, arguments, _client())

    return server


async def _async_run() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run() -> None:
    import asyncio

    asyncio.run(_async_run())
