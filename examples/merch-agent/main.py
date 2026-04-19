from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


AGENT_NAME = "merch-agent"
DEFAULT_QUERY = "Show me top 10 products"
DEFAULT_SEARCH_QUERY = "revenue"


def _ensure_repo_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    for relative in ("sdk", "integrations"):
        candidate = repo_root / relative
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
    return repo_root


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
    question: str = DEFAULT_QUERY,
    search_query: str = DEFAULT_SEARCH_QUERY,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    if dry_run:
        return {
            "agent": AGENT_NAME,
            "mode": "dry-run",
            "question": question,
            "steps": [
                "Fetch revenue metric for the last 24 hours",
                "Run a natural-language ranking query",
                "Paginate through the ranked rows",
                "Search the catalog for a merch keyword",
                "Render a merch summary",
            ],
            "expected_output": (
                "A merch snapshot with revenue, ranked products, pagination, and catalog hits."
            ),
        }

    _ensure_repo_paths()

    import httpx
    from agentflow import AgentFlowClient

    resolved_base_url = _resolve_base_url(base_url)
    resolved_api_key = _resolve_api_key(api_key)
    client = AgentFlowClient(resolved_base_url, api_key=resolved_api_key, timeout=30.0)
    revenue = client.get_metric("revenue", window="24h")
    first_page = client.query(question, limit=5)
    pages = list(client.paginate(question, page_size=5))

    with httpx.Client(
        base_url=resolved_base_url,
        headers={"X-API-Key": resolved_api_key},
        timeout=30.0,
    ) as http:
        search = http.get("/v1/search", params={"q": search_query, "limit": 3}).json()

    response = (
        f"Revenue in the last 24h is {revenue.value}{revenue.unit}. "
        f"Query returned {len(first_page.answer) if isinstance(first_page.answer, list) else 0} "
        f"rows on page one across {len(pages)} pages. "
        f"Top search hit: {search['results'][0]['id'] if search.get('results') else 'none'}."
    )

    return {
        "agent": AGENT_NAME,
        "mode": "live-sdk",
        "question": question,
        "search_query": search_query,
        "revenue_24h": revenue.value,
        "page_count": len(pages),
        "first_page_size": len(first_page.answer) if isinstance(first_page.answer, list) else 0,
        "top_search_hit": search["results"][0]["id"] if search.get("results") else None,
        "response": response,
        "steps": [
            "Fetched revenue metric",
            "Ran the merch ranking query",
            "Paginated through the query results",
            "Fetched search hits for the merch keyword",
            "Rendered a merch summary",
        ],
        "expected_output": (
            "A JSON merch brief with KPI context, ranked answers, and a searchable product lead."
        ),
    }


def run_crewai_demo(
    *,
    question: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    _ensure_repo_paths()

    try:
        from crewai import Agent, Crew, Task
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("CrewAI mode requires 'crewai' and 'crewai-tools'.") from exc

    from agentflow_integrations.crewai import get_agentflow_tools

    tools = get_agentflow_tools(
        _resolve_base_url(base_url),
        api_key=_resolve_api_key(api_key),
    )
    analyst = Agent(
        role="Merchandising Analyst",
        goal="Answer merch questions with live AgentFlow data.",
        backstory="You help merch teams explain revenue and product performance.",
        tools=tools,
        verbose=True,
    )
    task = Task(
        description=question,
        expected_output="A short merch summary grounded in live AgentFlow data.",
        agent=analyst,
    )
    crew = Crew(agents=[analyst], tasks=[task], verbose=True)
    result = crew.kickoff()

    return {
        "agent": AGENT_NAME,
        "mode": "live-crewai",
        "question": question,
        "response": str(result),
        "steps": [
            "Initialized CrewAI tools backed by AgentFlow",
            "Created a merch analyst agent",
            "Ran the merch task through CrewAI",
        ],
        "expected_output": "A CrewAI-generated merch summary backed by AgentFlow tools.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AgentFlow merch-agent example.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--question", default=DEFAULT_QUERY)
    parser.add_argument("--search-query", default=DEFAULT_SEARCH_QUERY)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--framework",
        choices=("sdk", "crewai"),
        default="sdk",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        payload = run_demo(
            dry_run=True,
            question=args.question,
            search_query=args.search_query,
        )
    elif args.framework == "crewai":
        payload = run_crewai_demo(
            question=args.question,
            base_url=args.base_url,
            api_key=args.api_key,
        )
    else:
        payload = run_demo(
            question=args.question,
            search_query=args.search_query,
            base_url=args.base_url,
            api_key=args.api_key,
        )

    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
