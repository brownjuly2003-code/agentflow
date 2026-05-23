from pathlib import Path

import click
import jinja2
import yaml


BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "spec.yaml"
TEMPLATE_DIR = BASE_DIR / "raw_vault"
TEMPLATE_NAME = "satellites_template.sql.j2"


def load_spec() -> dict:
    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def render_satellites(out_dir: Path) -> int:
    spec = load_spec()
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(TEMPLATE_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for satellite in spec["satellites"]:
        sql = template.render(**satellite)
        target = out_dir / f"{satellite['name']}.sql"
        target.write_text(sql, encoding="utf-8", newline="\n")
        count += 1
    return count


@click.command()
@click.option(
    "--out-dir",
    default="raw_vault/satellites",
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory relative to warehouse/agentflow/dv2.",
)
def main(out_dir: Path) -> None:
    if not out_dir.is_absolute():
        out_dir = BASE_DIR / out_dir
    count = render_satellites(out_dir)
    click.echo(f"Generated {count} satellite DDL files into {out_dir}")


if __name__ == "__main__":
    main()
