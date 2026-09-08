# Quickstart

This path sets up AgentFlow, starts the local API, and proves that it can answer
a health request. The recommended first run needs No Docker services or
provider API keys after package installation.

Stop here once the API answers. Use the [deployment walkthrough](deployment.md)
for other runtime profiles, the [API walkthrough](api/index.md) for useful
reads, the [full API reference](api-reference.md) for exact request and response
contracts, and the [contributor guide](contributing.md) for repository and
documentation work.

## Prerequisites

- Python `3.11+`
- Git

## Clone and set up

=== "PowerShell"

    ```powershell
    git clone https://github.com/brownjuly2003-code/agentflow.git
    cd agentflow
    . .\scripts\setup.ps1
    ```

=== "macOS / Linux"

    ```bash
    git clone https://github.com/brownjuly2003-code/agentflow.git
    cd agentflow
    source ./scripts/setup.sh
    ```

## Start the demo API with No Docker

The cross-platform runner prepares demo data and starts the API on
`http://localhost:8000`:

```bash
python scripts/demo_local.py
```

The command runs in the foreground. Leave it open while checking the service
from another terminal.

## Verify the first run

```bash
curl http://localhost:8000/v1/health
```

Expect HTTP `200` with an overall healthy status. The exact payload and error
contract belong to the
[health reference](api-reference.md#get-v1health).

## Continue by task

| Next task | Detailed owner |
| --- | --- |
| Prepare data without a server or choose a container-backed profile | [Deployment walkthrough](deployment.md) |
| Discover data, read an entity, or run a query | [API walkthrough](api/index.md) |
| Check authentication, parameters, response fields, or errors | [Full API reference](api-reference.md) |
| Preview this site or verify a repository change | [Contributor guide](contributing.md) |
