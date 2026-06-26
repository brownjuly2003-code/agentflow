from pathlib import Path

import click
import jinja2
import yaml

try:
    from .dialects import clickhouse_to_postgres_type
except ImportError:  # run as a plain script (python generate_satellites.py)
    from dialects import clickhouse_to_postgres_type


BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "spec.yaml"
TEMPLATE_DIR = BASE_DIR / "raw_vault"

# dialect -> (template, default output dir relative to dv2/)
DIALECTS: dict[str, tuple[str, str]] = {
    "clickhouse": ("satellites_template.sql.j2", "raw_vault/satellites"),
    "postgres": ("satellites_template_pg.sql.j2", "postgres/satellites"),
}


def load_spec() -> dict:
    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        raise ValueError("spec.yaml must contain a mapping")
    return spec


def render_satellites(out_dir: Path, dialect: str = "clickhouse") -> int:
    template_name, _ = DIALECTS[dialect]
    env = jinja2.Environment(  # noqa: S701 — emits SQL DDL; HTML autoescaping would corrupt it
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["pg_type"] = clickhouse_to_postgres_type
    template = env.get_template(template_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for satellite in load_spec()["satellites"]:
        sql = template.render(**satellite)
        target = out_dir / f"{satellite['name']}.sql"
        target.write_text(sql, encoding="utf-8", newline="\n")
        count += 1
    return count


@click.command()
@click.option(
    "--dialect",
    default="clickhouse",
    type=click.Choice(sorted(DIALECTS)),
    help="Target SQL dialect for the generated satellite DDL.",
)
@click.option(
    "--out-dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory relative to warehouse/agentflow/dv2 (defaults per dialect).",
)
def main(dialect: str, out_dir: Path | None) -> None:
    target = out_dir if out_dir is not None else Path(DIALECTS[dialect][1])
    if not target.is_absolute():
        target = BASE_DIR / target
    count = render_satellites(target, dialect)
    click.echo(f"Generated {count} {dialect} satellite DDL files into {target}")


if __name__ == "__main__":
    main()
