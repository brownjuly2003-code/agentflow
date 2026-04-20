import json
import os
from pathlib import Path
from typing import Any, cast

import click
from rich.console import Console
from rich.table import Table

from agentflow import AgentFlowClient
from agentflow.exceptions import AgentFlowError

_INIT_TEMPLATES: dict[str, dict[str, Any]] = {
    "basic": {
        "description": "simple Python agent",
        "next_steps": [
            "pip install -r requirements.txt",
            "python main.py",
        ],
    },
    "langchain": {
        "description": "LangChain agent with AgentFlow tools",
        "next_steps": [
            "pip install -r requirements.txt",
            "export OPENAI_API_KEY=...",
            "python main.py",
        ],
    },
    "crewai": {
        "description": "CrewAI agent with AgentFlow tools",
        "next_steps": [
            "pip install -r requirements.txt",
            "python main.py",
        ],
    },
    "vercel-ai": {
        "description": "Next.js app with Vercel AI SDK + AgentFlow",
        "next_steps": [
            "npm install",
            "npm run dev",
        ],
    },
}


def _resolve_config(url: str | None, key: str | None) -> tuple[str, str]:
    return (
        url or os.environ.get("AGENTFLOW_URL", "http://localhost:8000"),
        key or os.environ.get("AGENTFLOW_API_KEY", ""),
    )


def get_client(url: str | None, key: str | None) -> AgentFlowClient:
    resolved_url, resolved_key = _resolve_config(url, key)
    return AgentFlowClient(resolved_url, resolved_key)


def _console() -> Console:
    return Console(file=click.get_text_stream("stdout"), soft_wrap=True)


def _emit_json(payload: Any) -> None:
    click.echo(json.dumps(payload, indent=2, default=str))


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return "(not set)"
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{api_key[:2]}{'*' * (len(api_key) - 4)}{api_key[-2:]}"


def _format_number(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _format_currency(value: Any, currency: str | None) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    if currency == "USD":
        return f"${value:,.2f}"
    if currency:
        return f"{value:,.2f} {currency}"
    return f"{value:,.2f}"


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _template_root() -> Path:
    return Path(__file__).resolve().with_name("templates")


def _render_template(content: str, project_name: str, base_url: str, api_key: str) -> str:
    return (
        content.replace("__PROJECT_NAME__", project_name)
        .replace("__BASE_URL__", base_url)
        .replace("__API_KEY__", api_key)
    )


def _scaffold_project(
    template_name: str,
    project_dir: Path,
    project_name: str,
    base_url: str,
    api_key: str,
) -> list[str]:
    template_dir = _template_root() / template_name
    if not template_dir.exists():
        raise click.ClickException(f"Template '{template_name}' is not available.")

    created_files: list[str] = []
    for source_path in sorted(template_dir.rglob("*")):
        if source_path.is_dir():
            continue
        relative_path = source_path.relative_to(template_dir)
        target_path = project_dir.joinpath(
            *[
                part[:-5] if part.endswith(".tmpl") else part
                for part in relative_path.parts
            ]
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render_template(
            source_path.read_text(encoding="utf-8"),
            project_name,
            base_url,
            api_key,
        )
        with target_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        created_files.append(target_path.relative_to(project_dir.parent).as_posix())
    return created_files


def _request(
    ctx: click.Context,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            ctx.obj["client"]._request(method, path, params=params, json=payload),
        )
    except AgentFlowError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group()
@click.option(
    "--url",
    default=None,
    envvar="AGENTFLOW_URL",
    show_envvar=True,
    help="Base URL.",
)
@click.option(
    "--key",
    default=None,
    envvar="AGENTFLOW_API_KEY",
    show_envvar=True,
    help="API key.",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
@click.option("--quiet", is_flag=True, help="Suppress headers and decorations.")
@click.pass_context
def cli(ctx: click.Context, url: str | None, key: str | None, as_json: bool, quiet: bool):
    resolved_url, resolved_key = _resolve_config(url, key)
    ctx.ensure_object(dict)
    ctx.obj["client"] = get_client(resolved_url, resolved_key)
    ctx.obj["json"] = as_json
    ctx.obj["quiet"] = quiet
    ctx.obj["url"] = resolved_url
    ctx.obj["key"] = resolved_key


@cli.command()
@click.pass_context
def health(ctx: click.Context):
    payload = _request(ctx, "GET", "/v1/health")
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    if not ctx.obj["quiet"]:
        click.echo(f"Pipeline status: {payload.get('status', 'unknown')}")

    table = Table(show_header=not ctx.obj["quiet"])
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Details")
    for component in payload.get("components", []):
        table.add_row(
            str(component.get("name", "")),
            str(component.get("status", "")),
            str(component.get("message", "")),
        )
    _console().print(table)


@cli.command()
@click.argument("entity_type")
@click.argument("entity_id")
@click.pass_context
def entity(ctx: click.Context, entity_type: str, entity_id: str):
    payload = _request(ctx, "GET", f"/v1/entity/{entity_type}/{entity_id}")
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    data = dict(payload.get("data", {}))
    click.echo(f"{entity_type.title()} {entity_id}")

    ordered_lines: list[tuple[str, str]] = []
    if "status" in data:
        ordered_lines.append(("Status", _stringify(data.pop("status"))))
    if "total_amount" in data:
        ordered_lines.append(
            (
                "Total",
                _format_currency(data.pop("total_amount"), data.get("currency")),
            )
        )
    if "customer_id" in data:
        ordered_lines.append(("Customer", _stringify(data.pop("customer_id"))))
    elif "user_id" in data:
        ordered_lines.append(("User", _stringify(data.pop("user_id"))))
    if "items_count" in data:
        ordered_lines.append(("Items", _format_number(data.pop("items_count"))))
    if "created_at" in data:
        ordered_lines.append(("Created", _stringify(data.pop("created_at"))))

    for label, value in ordered_lines:
        click.echo(f"{label}: {value}")

    for key, value in data.items():
        if key in {"order_id", "currency"}:
            continue
        click.echo(f"{key.replace('_', ' ').title()}: {_stringify(value)}")


@cli.command()
@click.argument("name")
@click.option("--window", default="1h", show_default=True)
@click.pass_context
def metric(ctx: click.Context, name: str, window: str):
    payload = _request(ctx, "GET", f"/v1/metrics/{name}", params={"window": window})
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    click.echo(f"Metric: {name} ({window} window)")
    click.echo(f"Value: {_format_currency(payload.get('value'), payload.get('unit'))}")
    click.echo(f"Unit: {payload.get('unit', '')}")
    click.echo(f"As of: {payload.get('computed_at', '')}")


@cli.command()
@click.argument("question")
@click.pass_context
def query(ctx: click.Context, question: str):
    payload = _request(ctx, "POST", "/v1/query", payload={"question": question})
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    answer = payload.get("answer")
    if isinstance(answer, list) and answer and all(isinstance(item, dict) for item in answer):
        table = Table(show_header=not ctx.obj["quiet"])
        for column in answer[0]:
            table.add_column(str(column))
        for row in answer:
            table.add_row(*[_stringify(row.get(column, "")) for column in answer[0]])
        _console().print(table)
    else:
        click.echo(_stringify(answer))

    if payload.get("sql") and not ctx.obj["quiet"]:
        click.echo(f"SQL: {payload['sql']}")


@cli.command()
@click.argument("terms")
@click.pass_context
def search(ctx: click.Context, terms: str):
    payload = _request(ctx, "GET", "/v1/search", params={"q": terms})
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    table = Table(show_header=not ctx.obj["quiet"])
    table.add_column("Type")
    table.add_column("ID")
    table.add_column("Entity")
    table.add_column("Score")
    table.add_column("Snippet")
    for result in payload.get("results", []):
        table.add_row(
            str(result.get("type", "")),
            str(result.get("id", "")),
            str(result.get("entity_type", "")),
            _format_number(result.get("score", "")),
            str(result.get("snippet", "")),
        )
    _console().print(table)


@cli.command()
@click.pass_context
def catalog(ctx: click.Context):
    payload = _request(ctx, "GET", "/v1/catalog")
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    entities = Table(
        title=None if ctx.obj["quiet"] else "Entities",
        show_header=not ctx.obj["quiet"],
    )
    entities.add_column("Entity")
    entities.add_column("Primary Key")
    entities.add_column("Description")
    for name, details in payload.get("entities", {}).items():
        entities.add_row(
            str(name),
            str(details.get("primary_key", "")),
            str(details.get("description", "")),
        )
    _console().print(entities)

    metrics = Table(title=None if ctx.obj["quiet"] else "Metrics", show_header=not ctx.obj["quiet"])
    metrics.add_column("Metric")
    metrics.add_column("Unit")
    metrics.add_column("Windows")
    for name, details in payload.get("metrics", {}).items():
        metrics.add_row(
            str(name),
            str(details.get("unit", "")),
            ", ".join(details.get("available_windows", [])),
        )
    _console().print(metrics)


@cli.command()
@click.pass_context
def slo(ctx: click.Context):
    payload = _request(ctx, "GET", "/v1/slo")
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    table = Table(show_header=not ctx.obj["quiet"])
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Current")
    table.add_column("Target")
    table.add_column("Budget")
    table.add_column("Window")
    for item in payload.get("slos", []):
        table.add_row(
            str(item.get("name", "")),
            str(item.get("status", "")),
            _format_number(item.get("current", "")),
            _format_number(item.get("target", "")),
            _format_number(item.get("error_budget_remaining", "")),
            f"{item.get('window_days', '')}d",
        )
    _console().print(table)


@cli.command()
@click.option("--type", "event_type", default=None)
@click.pass_context
def stream(ctx: click.Context, event_type: str | None):
    params = {"event_type": event_type} if event_type else None
    if not ctx.obj["quiet"]:
        click.echo("Streaming events. Press Ctrl+C to stop.")

    try:
        with ctx.obj["client"]._client.stream(
            "GET",
            "/v1/stream/events",
            params=params,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                if ctx.obj["json"]:
                    _emit_json(payload)
                else:
                    click.echo(json.dumps(payload, default=str))
    except KeyboardInterrupt:
        if not ctx.obj["quiet"]:
            click.echo("Stream stopped.")
    except AgentFlowError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command()
@click.pass_context
def config(ctx: click.Context):
    payload = {
        "base_url": ctx.obj["url"],
        "api_key": _mask_api_key(ctx.obj["key"]),
    }
    if ctx.obj["json"]:
        _emit_json(payload)
        return

    click.echo(f"Base URL: {payload['base_url']}")
    click.echo(f"API Key: {payload['api_key']}")


@cli.command("init")
@click.option("--name", default=None, help="Project directory name.")
@click.option("--base-url", default=None, help="AgentFlow base URL.")
@click.option("--api-key", default=None, help="AgentFlow API key.")
@click.option(
    "--template",
    "template_name",
    default=None,
    type=click.Choice(list(_INIT_TEMPLATES), case_sensitive=False),
    help="Project template.",
)
@click.option("--non-interactive", is_flag=True, help="Disable prompts.")
@click.pass_context
def init_command(
    ctx: click.Context,
    name: str | None,
    base_url: str | None,
    api_key: str | None,
    template_name: str | None,
    non_interactive: bool,
):
    resolved_name = name
    resolved_base_url = base_url or ctx.obj["url"] or "http://localhost:8000"
    resolved_api_key = api_key or ctx.obj["key"] or ""
    resolved_template = template_name or "basic"

    if not non_interactive:
        click.echo("AgentFlow Project Setup")
        click.echo("=======================")
        resolved_name = resolved_name or click.prompt("Project name")
        resolved_base_url = click.prompt(
            "Base URL",
            default=resolved_base_url,
            show_default=True,
        )
        resolved_api_key = click.prompt(
            "API key",
            default=resolved_api_key,
            hide_input=True,
            show_default=False,
        )
        click.echo("Template:")
        for option_name, details in _INIT_TEMPLATES.items():
            click.echo(f"  {option_name:<10} - {details['description']}")
        resolved_template = click.prompt(
            "Template",
            default=resolved_template,
            show_default=True,
            show_choices=False,
            type=click.Choice(list(_INIT_TEMPLATES), case_sensitive=False),
        )
        click.echo()
    else:
        if not resolved_name:
            raise click.UsageError("--name is required in non-interactive mode.")

    project_dir = Path.cwd() / cast(str, resolved_name)
    if project_dir.exists():
        raise click.ClickException(f"Target directory '{project_dir.name}' already exists.")

    project_dir.mkdir()
    click.echo(f"Creating {project_dir.name}/")
    created_files = _scaffold_project(
        resolved_template,
        project_dir,
        project_dir.name,
        resolved_base_url,
        cast(str, resolved_api_key),
    )
    for created_file in created_files:
        click.echo(f"Created {created_file}")

    click.echo()
    click.echo("Next steps:")
    click.echo(f"  cd {project_dir.name}")
    for step in _INIT_TEMPLATES[resolved_template]["next_steps"]:
        click.echo(f"  {step}")
