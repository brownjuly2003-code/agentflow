from __future__ import annotations

import argparse
import json
import os
from typing import Any

AGENT_NAME = "support-agent"
DEFAULT_ORDER_ID = "ORD-20260404-1001"
DEFAULT_QUERY = "Where is order ORD-20260404-1001 right now?"


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
        or os.getenv("AGENTFLOW_SUPPORT_API_KEY")
        or os.getenv("AGENTFLOW_API_KEY")
        or "af-prod-agent-support-abc123"
    )


def run_demo(
    *,
    dry_run: bool = False,
    question: str = DEFAULT_QUERY,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    if dry_run:
        return {
            "agent": AGENT_NAME,
            "mode": "dry-run",
            "question": question,
            "steps": [
                f"Look up {DEFAULT_ORDER_ID}",
                "Fetch the related user profile",
                "Read active_sessions for the last hour",
                "Assemble a support-ready answer with live data",
            ],
            "expected_output": (
                "A short answer that cites the current order status, customer profile, "
                "and active session context."
            ),
        }

    from agentflow import AgentFlowClient

    client = AgentFlowClient(
        _resolve_base_url(base_url),
        api_key=_resolve_api_key(api_key),
        timeout=30.0,
    )
    order = client.get_order(DEFAULT_ORDER_ID)
    user = client.get_user(order.user_id)
    active_sessions = client.get_metric("active_sessions", window="1h")
    response = (
        f"Order {order.order_id} is {order.status}. "
        f"The customer is {user.user_id} with {user.total_orders} lifetime orders "
        f"and {active_sessions.value} active sessions in the last hour."
    )

    return {
        "agent": AGENT_NAME,
        "mode": "live-sdk",
        "question": question,
        "order_id": order.order_id,
        "status": order.status,
        "user_id": user.user_id,
        "user_total_orders": user.total_orders,
        "active_sessions_1h": active_sessions.value,
        "response": response,
        "steps": [
            "Fetched the live order entity",
            "Fetched the linked user entity",
            "Fetched the active_sessions metric",
            "Rendered a support summary",
        ],
        "expected_output": (
            "A support-ready order summary grounded in the latest entity and metric data."
        ),
    }


def run_langchain_demo(
    *,
    question: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    try:
        from langchain.agents import AgentType, initialize_agent
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "LangChain mode requires 'langchain' and 'langchain-openai'."
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):  # pragma: no cover
        raise RuntimeError("Set OPENAI_API_KEY before running --framework langchain.")

    from agentflow_integrations.langchain import AgentFlowToolkit

    toolkit = AgentFlowToolkit(
        _resolve_base_url(base_url),
        api_key=_resolve_api_key(api_key),
    )
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = initialize_agent(
        toolkit.get_tools(),
        llm,
        agent=AgentType.OPENAI_FUNCTIONS,
        verbose=True,
    )
    result = agent.invoke({"input": question})

    return {
        "agent": AGENT_NAME,
        "mode": "live-langchain",
        "question": question,
        "response": result["output"] if isinstance(result, dict) else str(result),
        "steps": [
            "Initialized LangChain tools backed by AgentFlow",
            "Asked the LLM to plan tool calls",
            "Returned the tool-grounded support answer",
        ],
        "expected_output": (
            "A LangChain-generated support answer grounded in the AgentFlow toolkit."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AgentFlow support-agent example.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--question", default=DEFAULT_QUERY)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--framework",
        choices=("sdk", "langchain"),
        default="sdk",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        payload = run_demo(dry_run=True, question=args.question)
    elif args.framework == "langchain":
        payload = run_langchain_demo(
            question=args.question,
            base_url=args.base_url,
            api_key=args.api_key,
        )
    else:
        payload = run_demo(
            question=args.question,
            base_url=args.base_url,
            api_key=args.api_key,
        )

    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
