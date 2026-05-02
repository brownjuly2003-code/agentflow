# support-agent

Support workflow for order-status questions. The default mode uses the local SDK only so it can run against the demo stack without extra LLM setup. An optional LangChain mode is included for teams that want a framework-backed agent loop.

## Prerequisites

- Python 3.11+
- Running AgentFlow API at `http://localhost:8000` or `AGENTFLOW_BASE_URL`
- `AGENTFLOW_SUPPORT_API_KEY` or `AGENTFLOW_API_KEY` for auth-enabled APIs; local `make demo` uses open auth defaults
- Optional for `--framework langchain`: `langchain`, `langchain-openai`, and `OPENAI_API_KEY`

## Setup

From the repository root:

```bash
python -m pip install -e sdk
python -m pip install -e integrations
```

Optional LangChain extras:

```bash
python -m pip install langchain langchain-openai
```

## Run

```bash
cd examples/support-agent
python main.py --dry-run
python main.py
python main.py --framework langchain --question "Where is order ORD-20260404-1001 right now?"
```

## Expected Output

The default run prints JSON with the current order status, linked user details, the latest `active_sessions` metric, and a short support-ready answer. `--dry-run` prints the same contract without network calls. LangChain mode prints a tool-grounded response generated through the AgentFlow toolkit.
