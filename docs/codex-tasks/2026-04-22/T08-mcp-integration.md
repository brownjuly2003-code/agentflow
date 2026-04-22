# T08 — MCP integration

**Priority:** P3 · **Estimate:** 1 день

## Goal

Добавить `integrations/mcp/` с MCP-сервером, exposing AgentFlow API как MCP tools для Claude Desktop / Cursor / Windsurf.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Уже есть интеграции `integrations/langchain/` и `integrations/llamaindex/` — использовать как образец структуры
- MCP (Model Context Protocol, Anthropic) — открытый стандарт для подключения tools к LLM-клиентам
- Python SDK: `mcp` на PyPI (`pip install mcp`)
- AgentFlow Python SDK: `sdk/agentflow/` — использовать его `AgentFlowClient` / `AsyncAgentFlowClient`, НЕ дублировать логику HTTP

## Deliverables

1. **Новый sub-package** `integrations/mcp/`:
   ```
   integrations/mcp/
     pyproject.toml
     README.md
     src/agentflow_mcp/
       __init__.py
       __main__.py
       server.py
     tests/
       test_server.py
       conftest.py
   ```

2. **`integrations/mcp/pyproject.toml`**:
   - Package name: `agentflow-mcp`
   - Version: `1.0.1` (синхронно с главным проектом, см. T02)
   - Dependencies: `agentflow-sdk>=1.0.1`, `mcp>=0.9`, `pydantic>=2.0`
   - Dev: `pytest`, `pytest-asyncio`

3. **`src/agentflow_mcp/server.py`**:
   - Класс `AgentFlowMCPServer` использующий stdio transport
   - Tools (через `mcp.server.Server` + `@server.list_tools()` / `@server.call_tool()`):
     - `entity_lookup(entity_type: str, entity_id: str)` → JSON entity
     - `metric_query(name: str, window: str)` → metric value + timestamp
     - `nl_query(question: str)` → query result (использует `/v1/query`)
     - `health_check()` → dict component health
     - `list_entities()` → available entity types из `/v1/catalog`
   - Конфиг через env:
     - `AGENTFLOW_API_URL` (default `http://localhost:8000`)
     - `AGENTFLOW_API_KEY` (optional)
     - `AGENTFLOW_TIMEOUT_SECONDS` (default `10`)

4. **`src/agentflow_mcp/__main__.py`**:
   ```python
   from .server import run
   if __name__ == "__main__":
       run()
   ```
   + `run()` поднимает stdio server

5. **`tests/test_server.py`**:
   - Unit tests для каждого tool handler
   - Mock `AgentFlowClient` через `pytest-mock`
   - Проверка: tool schema valid (через `mcp` validation), handler возвращает ожидаемую структуру, errors маппятся в MCP error codes

6. **`integrations/mcp/README.md`**:
   - Quick start:
     ```json
     // claude_desktop_config.json
     {
       "mcpServers": {
         "agentflow": {
           "command": "python",
           "args": ["-m", "agentflow_mcp"],
           "env": {
             "AGENTFLOW_API_URL": "http://localhost:8000",
             "AGENTFLOW_API_KEY": "your-key"
           }
         }
       }
     }
     ```
   - Список tools с описаниями и примерами
   - Troubleshooting (server не видится в Claude Desktop → проверить логи)

7. **Обновить** корневой `README.md` — в секцию Integrations добавить MCP с одной строкой

8. Коммит `feat(integrations): add MCP server for Claude Desktop / Cursor / Windsurf`

## Acceptance

- `cd integrations/mcp && pip install -e . && pytest` — все тесты зелёные
- Локальный smoke:
  1. Запустить AgentFlow local demo: `make demo-run` (или эквивалент)
  2. Запустить `python -m agentflow_mcp` в отдельной shell — сервер стартует без ошибок
  3. Через `mcp` CLI client (если доступен) или через тест `tests/test_server.py::test_integration_live` (skip by default, `@pytest.mark.live`) проверить что tools вызываются и возвращают данные
- README пример рабочий — команда `python -m agentflow_mcp` запускается
- `mcp validate` (если CLI есть) — server schema валидный

## Notes

- Tool descriptions — четкие и LLM-friendly: что делает, какие аргументы, когда использовать. Следовать patterns из MCP docs (https://modelcontextprotocol.io/docs)
- НЕ дублировать HTTP-логику — все запросы через существующий `AgentFlowClient`. Если SDK не покрывает какой-то endpoint — расширить SDK, не обходить
- Если `mcp` зависимость неустойчива / API меняется — пометить integration как `experimental` в README с disclaimer
- Errors: AgentFlow 404 → MCP `ResourceNotFound`, 5xx → `InternalError`, timeout → `Timeout`
- Tests должны покрывать error paths отдельно (network failure, invalid entity_type, timeout)
