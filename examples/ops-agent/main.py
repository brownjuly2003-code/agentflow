from __future__ import annotations

import argparse
import json
import os
from typing import Any

AGENT_NAME = "ops-agent"


def _resolve_base_url(value: str | None = None) -> str:
    return (
        value
        or os.getenv("AGENTFLOW_BASE_URL")
        or os.getenv("AGENTFLOW_URL")
        or "http://localhost:8000"
    ).rstrip("/")


def _resolve_api_key(value: str | None = None) -> str:
    return (
        value
        or os.getenv("AGENTFLOW_OPS_API_KEY")
        or os.getenv("AGENTFLOW_API_KEY")
        or "af-prod-agent-ops-def456"
    )


def run_demo(
    *,
    dry_run: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    if dry_run:
        return {
            "agent": AGENT_NAME,
            "mode": "dry-run",
            "steps": [
                "Check /v1/health",
                "Fetch error_rate metric",
                "Inspect /v1/deadletter",
                "Inspect /v1/slo",
                "Render an operational summary",
            ],
            "expected_output": (
                "A compact incident summary with health, SLO, dead-letter, and error-rate data."
            ),
        }

    import httpx
    from agentflow import AgentFlowClient

    resolved_base_url = _resolve_base_url(base_url)
    resolved_api_key = _resolve_api_key(api_key)
    client = AgentFlowClient(resolved_base_url, api_key=resolved_api_key, timeout=30.0)
    health = client.health()
    error_rate = client.get_metric("error_rate", window="1h")

    with httpx.Client(
        base_url=resolved_base_url,
        headers={"X-API-Key": resolved_api_key},
        timeout=30.0,
    ) as http:
        deadletter = http.get("/v1/deadletter").json()
        slo = http.get("/v1/slo").json()

    failed_items = deadletter.get("items", [])
    slo_items = slo.get("slos", [])
    at_risk = [item["name"] for item in slo_items if item["status"] != "healthy"]
    response = (
        f"Pipeline health is {health.status}. "
        f"Current error_rate is {error_rate.value}{error_rate.unit}. "
        f"There are {len(failed_items)} failed dead-letter items. "
        f"SLOs needing attention: {', '.join(at_risk) if at_risk else 'none'}."
    )

    return {
        "agent": AGENT_NAME,
        "mode": "live-sdk",
        "health_status": health.status,
        "error_rate_1h": error_rate.value,
        "deadletter_failed": len(failed_items),
        "at_risk_slos": at_risk,
        "response": response,
        "steps": [
            "Fetched pipeline health",
            "Fetched error_rate metric",
            "Fetched dead-letter queue summary",
            "Fetched SLO status",
            "Rendered an ops summary",
        ],
        "expected_output": (
            "A single JSON summary that highlights system health, risk, and queue pressure."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AgentFlow ops-agent example.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args(argv)

    payload = run_demo(
        dry_run=args.dry_run,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
