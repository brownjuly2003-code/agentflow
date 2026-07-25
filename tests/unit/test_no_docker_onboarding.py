"""Docs and setup scripts must lead to the executable no-Docker demo."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_COMMAND = "python scripts/demo_local.py"


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_primary_docs_lead_with_the_no_docker_runner() -> None:
    for relative_path in ("README.md", "docs/quickstart.md", "docs/deployment.md"):
        text = _text(relative_path)
        assert LOCAL_COMMAND in text, relative_path
        assert "No Docker" in text, relative_path

    quick_start = _text("README.md").split("## Architecture", 1)[0]
    assert quick_start.index(LOCAL_COMMAND) < quick_start.index("make demo")
    assert "Docker Compose (optional" in quick_start


def test_setup_scripts_point_to_the_local_runner() -> None:
    for relative_path in ("scripts/setup.ps1", "scripts/setup.sh"):
        text = _text(relative_path)
        assert LOCAL_COMMAND in text, relative_path


def test_makefile_has_a_no_docker_alias() -> None:
    makefile = _text("Makefile")
    target = makefile.split("demo-local:", 1)[1].split("\n\n", 1)[0]

    assert LOCAL_COMMAND in target
    assert "docker compose" not in target


def test_own_key_commands_keep_the_local_only_duckdb_profile() -> None:
    quick_start = _text("README.md").split("## Architecture", 1)[0]

    assert "SERVING_BACKEND=duckdb" in quick_start
    assert "AGENTFLOW_LOCAL_ONLY=true" in quick_start
    assert '$env:SERVING_BACKEND = "duckdb"' in quick_start
    assert '$env:AGENTFLOW_LOCAL_ONLY = "true"' in quick_start
