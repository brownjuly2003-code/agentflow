# merch-agent

Merchandising workflow for KPI snapshots, ranked product answers, and catalog discovery. The default mode uses the SDK plus direct search calls. An optional CrewAI mode is included if you want the same workflow behind an agent framework.

## Prerequisites

- Python 3.11+
- Running AgentFlow API at `http://localhost:8000` or `AGENTFLOW_BASE_URL`
- `AGENTFLOW_OPS_API_KEY` or `AGENTFLOW_API_KEY`
- Optional for `--framework crewai`: `crewai` and `crewai-tools`

## Setup

From the repository root:

```bash
python -m pip install -e sdk
python -m pip install -e integrations
```

Optional CrewAI extras:

```bash
python -m pip install crewai crewai-tools
```

## Run

```bash
cd examples/merch-agent
python main.py
python main.py --dry-run
python main.py --framework crewai --question "Summarize revenue and the top products for today."
```

## Expected Output

The default run prints JSON with the 24-hour revenue metric, the first page of ranked product results, pagination depth, a search hit for the merch keyword, and a short merch summary. `--dry-run` prints the execution plan only. CrewAI mode prints the agent-produced merch summary.
