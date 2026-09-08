"""Export the generated cross-SDK capability contract.

By default writes ``docs/sdk-capabilities.md`` from
``config/project_claims.toml``. With ``--check``, exits non-zero when the
tracked output does not match the manifest.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = Path("config/project_claims.toml")
GENERATED_ARTIFACT_PATHS = (Path("docs/sdk-capabilities.md"),)


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / SOURCE_PATH
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load {path.relative_to(root).as_posix()}: {exc}") from exc


def _render_sdk_capabilities(manifest: dict[str, Any]) -> str:
    rows = [
        "# SDK capability contract",
        "",
        "Generated from [`config/project_claims.toml`](../config/project_claims.toml) "
        "by `python scripts/export_sdk_capabilities.py`. Edit the manifest, not this table.",
        "",
        "| Capability | Python methods | TypeScript methods |",
        "| --- | --- | --- |",
    ]
    for capability in manifest["sdk"].get("capability", []):
        python_methods = ", ".join(f"`{name}`" for name in capability["python_methods"])
        typescript_methods = ", ".join(f"`{name}`" for name in capability["typescript_methods"])
        rows.append(f"| {capability['name']} | {python_methods} | {typescript_methods} |")
    rows.append("")
    return "\n".join(rows)


def _build_artifacts(root: Path, manifest: dict[str, Any]) -> list[tuple[Path, str]]:
    rendered = _render_sdk_capabilities(manifest)
    return [(root / relative, rendered) for relative in GENERATED_ARTIFACT_PATHS]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated SDK capability contract has drifted.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        manifest = _load_manifest(root)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    artifacts = _build_artifacts(root, manifest)

    if args.check:
        drift = [
            path.relative_to(root).as_posix()
            for path, expected in artifacts
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        if drift:
            sys.stderr.write(
                "SDK capability drift detected. Regenerate with "
                "`python scripts/export_sdk_capabilities.py` and commit:\n"
            )
            for relative in drift:
                sys.stderr.write(f"  - {relative}\n")
            return 1
        return 0

    for path, text in artifacts:
        _write_text(path, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
