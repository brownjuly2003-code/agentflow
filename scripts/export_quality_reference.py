"""Export the deterministic quality-gate reference.

By default writes ``docs/quality.md`` from ``config/project_claims.toml``.
With ``--check``, exits non-zero when the tracked reference does not match the
machine-readable quality claims.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = Path("config/project_claims.toml")
GENERATED_ARTIFACT_PATHS = (Path("docs/quality.md"),)


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / SOURCE_PATH
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        relative = path.relative_to(root).as_posix()
        raise ValueError(f"cannot load {relative}: {exc}") from exc


def _render_quality_reference(manifest: dict[str, Any]) -> str:
    quality = manifest["quality"]
    strict_status = "required" if quality["strict_documentation_build"] else "not required"
    rows = [
        "# AgentFlow quality gates",
        "",
        "Generated from [`config/project_claims.toml`](../config/project_claims.toml) "
        "by `python scripts/export_quality_reference.py`. Edit the manifest, not this list.",
        "",
        "## Enforced gates",
        f"- Project coverage floor: {quality['project_coverage_floor_percent']}%",
        f"- Patch coverage floor: {quality['patch_coverage_floor_percent']}%",
        f"- Critical-module coverage floor: {quality['critical_module_coverage_floor_percent']}%",
        f"- MkDocs strict build: {strict_status}",
        "",
        "## Verification",
        "",
        "- Regenerate this reference with `python scripts/export_quality_reference.py`.",
        "- Check tracked drift with `python scripts/export_quality_reference.py --check`.",
        "- Validate the claims against CI and Codecov configuration with "
        "`python scripts/validate_project_claims.py`.",
        "",
        "## Local quality snapshots",
        "",
        "- Coverage: published from source `coverage.xml` only by a host-specific snapshot "
        "when that artifact is fresh; this deterministic reference owns the configured "
        "floors above.",
        "",
        "Run `python scripts/quality_report.py --skip-docker --skip-dependency-scans` "
        "for a host- and time-specific report. Its default output is "
        "`.artifacts/quality/quality-report.md`, which is intentionally ignored.",
        "",
        "A local snapshot can depend on test collection, coverage age, security tools, "
        "and mutation, chaos, and load artifacts. It is not a cross-host current "
        "reference. The last tracked dynamic snapshot is preserved as "
        "[historical generated output](archive/quality-report-2026-07-23.md).",
        "",
    ]
    return "\n".join(rows)


def _build_artifacts(root: Path, manifest: dict[str, Any]) -> list[tuple[Path, str]]:
    rendered = _render_quality_reference(manifest)
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
        help="Fail if the generated quality-gate reference has drifted.",
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
                "Quality reference drift detected. Regenerate with "
                "`python scripts/export_quality_reference.py` and commit:\n"
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
