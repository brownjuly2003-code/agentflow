"""Guard the three-node deploy artifacts (ADR 0012 §11).

A malformed Space README frontmatter is a silent deploy failure (the HF Space
build rejects it), so these check the deploy-critical shape and that each
per-role README documents the environment that role needs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_THREE_NODE = _ROOT / "deploy" / "hf-space" / "three-node"


def _frontmatter(readme: Path) -> dict:
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{readme} is missing YAML frontmatter"
    _, block, _body = text.split("---\n", 2)
    return yaml.safe_load(block)


def test_deploy_runbook_exists() -> None:
    assert (_THREE_NODE / "DEPLOY.md").is_file()


def test_each_role_readme_has_valid_space_frontmatter() -> None:
    for role in ("center", "edge-spb", "edge-ekb"):
        readme = _THREE_NODE / role / "README.md"
        assert readme.is_file(), f"missing {readme}"
        meta = _frontmatter(readme)
        assert meta["sdk"] == "docker"
        assert meta["app_port"] == 8000
        assert meta["title"]


def test_center_readme_documents_center_role() -> None:
    text = (_THREE_NODE / "center" / "README.md").read_text(encoding="utf-8")
    assert "AGENTFLOW_NODE_ROLE" in text
    assert "`center`" in text
    assert "`msk`" in text
    # The honesty boundary must be stated so the artifact never over-claims.
    assert "scale profile" in text
    assert "ephemeral" in text.lower()


def test_edge_readmes_document_edge_role_and_center_url() -> None:
    for role, branch in (("edge-spb", "spb"), ("edge-ekb", "ekb")):
        text = (_THREE_NODE / role / "README.md").read_text(encoding="utf-8")
        assert "AGENTFLOW_NODE_ROLE" in text
        assert "`edge`" in text
        assert f"`{branch}`" in text
        assert "AGENTFLOW_NODE_CENTER_URL" in text
