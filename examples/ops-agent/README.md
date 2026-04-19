# ops-agent

Operations workflow for health, SLO, and dead-letter monitoring. This example stays framework-free and only uses the local SDK plus direct HTTP calls to operational endpoints.

## Prerequisites

- Python 3.11+
- Running AgentFlow API at `http://localhost:8000` or `AGENTFLOW_BASE_URL`
- `AGENTFLOW_OPS_API_KEY` or `AGENTFLOW_API_KEY`

## Setup

From the repository root:

```bash
python -m pip install -e sdk
```

## Run

```bash
cd examples/ops-agent
python main.py
python main.py --dry-run
```

## Expected Output

The script prints JSON with `health_status`, the latest `error_rate` metric, the number of failed dead-letter items, any non-healthy SLOs, and a short incident-style summary. `--dry-run` prints the same execution plan without network access.
