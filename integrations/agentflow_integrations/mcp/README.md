# AgentFlow MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes AgentFlow to Claude Desktop, Cursor, Windsurf, and any other
MCP-aware client. The server is a thin wrapper over
`agentflow.AgentFlowClient` — it does not reimplement HTTP or auth.

## Install

```bash
pip install -e "./integrations[mcp]"
```

This installs the `agentflow-mcp` console script and the `mcp` runtime.

## Run

```bash
AGENTFLOW_API_URL=http://localhost:8000 \
AGENTFLOW_API_KEY=your-key \
python -m agentflow_integrations.mcp
```

The process speaks MCP over stdio, so it is meant to be launched by an
MCP client rather than a human terminal.

## Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `AGENTFLOW_API_URL` | `http://localhost:8000` | AgentFlow API base URL. |
| `AGENTFLOW_API_KEY` | *unset* | Sent as `X-API-Key`. Empty is treated as unauthenticated. |
| `AGENTFLOW_TIMEOUT_SECONDS` | `10` | Per-request timeout. |

## Claude Desktop configuration

Add the following block to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agentflow": {
      "command": "python",
      "args": ["-m", "agentflow_integrations.mcp"],
      "env": {
        "AGENTFLOW_API_URL": "http://localhost:8000",
        "AGENTFLOW_API_KEY": "your-key"
      }
    }
  }
}
```

Restart Claude Desktop. The `agentflow` server should appear in the
tool inventory with the five tools listed below.

## Tools

| Tool | Purpose | Required args |
| --- | --- | --- |
| `entity_lookup` | Fetch a single entity (`order`, `user`, `product`, `session`). | `entity_type`, `entity_id` |
| `metric_query` | Read a business metric over a time window. | `name` (+ optional `window`) |
| `nl_query` | Ask a natural-language question; AgentFlow plans and runs the query. | `question` |
| `health_check` | Return pipeline health and freshness. | *(none)* |
| `list_entities` | Return the AgentFlow catalog (entity types, metrics, capabilities). | *(none)* |

## Error mapping

SDK exceptions are converted to structured JSON error payloads so the
MCP client receives a readable message:

| SDK exception | `error` code |
| --- | --- |
| `EntityNotFoundError` | `not_found` |
| `AuthError` | `auth` |
| `RateLimitError` | `rate_limit` |
| `DataFreshnessError` | `stale_data` |
| `AgentFlowError` | `agentflow` |
| `ValueError` (invalid args) | `invalid_argument` |

## Troubleshooting

- **Server not visible in Claude Desktop** — confirm `python -m
  agentflow_integrations.mcp` starts without an error when run directly
  (the process will block waiting for stdin — that is normal).
- **`Could not connect to AgentFlow API`** — start the API first
  (`make demo`) and re-check `AGENTFLOW_API_URL`.
- **`auth` errors** — set `AGENTFLOW_API_KEY` to a valid key issued by
  the AgentFlow auth manager.
