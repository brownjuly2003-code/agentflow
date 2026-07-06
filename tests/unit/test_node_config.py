"""Node config resolution + fail-fast validation (ADR 0012 / build contract §2).

Pure-logic half of the node invariants: role/branch/center-url/token
resolution and the boot-time guards. The full-app N1/N2 mounting behaviour is
in ``tests/integration/test_node_topology.py``.
"""

from __future__ import annotations

import pytest

from src.serving.node import (
    CENTER_BRANCH,
    EDGE_BRANCHES,
    NodeConfig,
    NodeConfigError,
    resolve_node_config,
)

_NODE_TOKEN = "test-node-token-value"  # noqa: S105 — test fixture, not a real secret


def test_standalone_when_role_unset() -> None:
    cfg = resolve_node_config({})
    assert cfg.role == "standalone"
    assert cfg.is_standalone
    assert cfg.branch is None
    assert cfg.center_url is None
    assert cfg.token is None


def test_standalone_when_role_blank() -> None:
    assert resolve_node_config({"AGENTFLOW_NODE_ROLE": "   "}).role == "standalone"


def test_standalone_ignores_stray_node_vars() -> None:
    # Strict superset (N1): a standalone node never validates branch/url/token,
    # so today's demo Space keeps booting even if unrelated env is present.
    cfg = resolve_node_config(
        {
            "AGENTFLOW_NODE_BRANCH": "spb",
            "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
        }
    )
    assert cfg.role == "standalone"
    assert cfg.branch is None


def test_role_is_case_insensitive() -> None:
    cfg = resolve_node_config({"AGENTFLOW_NODE_ROLE": "CENTER", "AGENTFLOW_NODE_TOKEN": "t"})
    assert cfg.role == "center"


def test_invalid_role_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="AGENTFLOW_NODE_ROLE"):
        resolve_node_config({"AGENTFLOW_NODE_ROLE": "hub", "AGENTFLOW_NODE_TOKEN": "t"})


def test_center_defaults_branch_to_msk() -> None:
    cfg = resolve_node_config(
        {"AGENTFLOW_NODE_ROLE": "center", "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN}
    )
    assert cfg.is_center
    assert cfg.branch == CENTER_BRANCH
    assert cfg.center_url is None  # the center does not emit
    assert cfg.token == _NODE_TOKEN


def test_center_explicit_msk_ok() -> None:
    cfg = resolve_node_config(
        {
            "AGENTFLOW_NODE_ROLE": "center",
            "AGENTFLOW_NODE_BRANCH": "msk",
            "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
        }
    )
    assert cfg.branch == "msk"


def test_center_wrong_branch_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="center node"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "center",
                "AGENTFLOW_NODE_BRANCH": "spb",
                "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            }
        )


def test_center_without_token_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="AGENTFLOW_NODE_TOKEN"):
        resolve_node_config({"AGENTFLOW_NODE_ROLE": "center"})


def test_center_ignores_center_url() -> None:
    cfg = resolve_node_config(
        {
            "AGENTFLOW_NODE_ROLE": "center",
            "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            "AGENTFLOW_NODE_CENTER_URL": "https://ignored.test",
        }
    )
    assert cfg.center_url is None


@pytest.mark.parametrize("branch", sorted(EDGE_BRANCHES))
def test_edge_valid(branch: str) -> None:
    cfg = resolve_node_config(
        {
            "AGENTFLOW_NODE_ROLE": "edge",
            "AGENTFLOW_NODE_BRANCH": branch,
            "AGENTFLOW_NODE_CENTER_URL": "https://liovina-agentflow-center.hf.space",
            "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
        }
    )
    assert cfg.is_edge
    assert cfg.branch == branch
    assert cfg.center_url == "https://liovina-agentflow-center.hf.space"
    assert cfg.token == _NODE_TOKEN


def test_edge_without_center_url_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="AGENTFLOW_NODE_CENTER_URL"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_BRANCH": "spb",
                "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            }
        )


def test_edge_without_token_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="AGENTFLOW_NODE_TOKEN"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_BRANCH": "spb",
                "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
            }
        )


def test_edge_rejects_center_branch() -> None:
    # msk is the center's branch; an edge must be a regional warehouse.
    with pytest.raises(NodeConfigError, match="edge node"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_BRANCH": "msk",
                "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
                "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            }
        )


def test_edge_rejects_unknown_branch() -> None:
    with pytest.raises(NodeConfigError, match="edge node"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_BRANCH": "tokyo",
                "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
                "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            }
        )


def test_edge_missing_branch_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="edge node"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
                "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN,
            }
        )


def test_whitespace_only_token_is_unset() -> None:
    with pytest.raises(NodeConfigError, match="AGENTFLOW_NODE_TOKEN"):
        resolve_node_config({"AGENTFLOW_NODE_ROLE": "center", "AGENTFLOW_NODE_TOKEN": "   "})


def test_token_value_preserved_verbatim() -> None:
    # The token is compared byte-for-byte on the center; internal whitespace and
    # surrounding structure must survive resolution untouched.
    token = "af-node- spaced -secret"  # noqa: S105 — test fixture, not a real secret
    cfg = resolve_node_config({"AGENTFLOW_NODE_ROLE": "center", "AGENTFLOW_NODE_TOKEN": token})
    assert cfg.token == token


def test_config_is_frozen() -> None:
    cfg = NodeConfig(role="standalone")
    with pytest.raises((AttributeError, TypeError)):
        cfg.role = "center"  # type: ignore[misc]


def test_center_token_equal_to_default_demo_key_fails_fast() -> None:
    # n4 (G2 audit): the well-known public demo API key must never double as
    # the node-federation bearer token.
    with pytest.raises(NodeConfigError, match="demo API key"):
        resolve_node_config({"AGENTFLOW_NODE_ROLE": "center", "AGENTFLOW_NODE_TOKEN": "demo-key"})


def test_edge_token_equal_to_default_demo_key_fails_fast() -> None:
    with pytest.raises(NodeConfigError, match="demo API key"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "edge",
                "AGENTFLOW_NODE_BRANCH": "spb",
                "AGENTFLOW_NODE_CENTER_URL": "https://example.test",
                "AGENTFLOW_NODE_TOKEN": "demo-key",
            }
        )


def test_token_equal_to_custom_demo_api_key_env_fails_fast() -> None:
    # DEMO_API_KEY overrides the default "demo-key" (src/serving/api/main.py) —
    # the guard must compare against whatever value is actually configured,
    # not just the hardcoded default.
    with pytest.raises(NodeConfigError, match="demo API key"):
        resolve_node_config(
            {
                "AGENTFLOW_NODE_ROLE": "center",
                "AGENTFLOW_NODE_TOKEN": "custom-demo-value",
                "DEMO_API_KEY": "custom-demo-value",
            }
        )


def test_token_distinct_from_demo_key_is_fine() -> None:
    cfg = resolve_node_config(
        {"AGENTFLOW_NODE_ROLE": "center", "AGENTFLOW_NODE_TOKEN": _NODE_TOKEN}
    )
    assert cfg.token == _NODE_TOKEN
