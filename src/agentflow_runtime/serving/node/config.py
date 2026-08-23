"""Resolve and validate the ``AGENTFLOW_NODE_*`` environment (ADR 0012 §2).

The node role is pure environment on top of the existing demo image. This
module is the single place that reads that environment, so a misconfigured
node fails fast at boot (``docs/three-node-demo-topology.md`` §2: "boot must
fail fast if an edge has role=edge but no center URL or no token") instead of
coming up half-wired.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

NodeRole = Literal["center", "edge", "standalone"]

# Legend mapping (ADR 0012 Decision 1): center = HQ ``msk``; the two live edge
# nodes are the RU regional warehouses ``spb`` / ``ekb``. Foreign branches
# (``dxb`` / ``ala``) are deliberately NOT live nodes (PII border), so they are
# absent here.
CENTER_BRANCH = "msk"
EDGE_BRANCHES = frozenset({"spb", "ekb"})
KNOWN_BRANCHES = frozenset({CENTER_BRANCH}) | EDGE_BRANCHES

_VALID_ROLES = frozenset({"center", "edge", "standalone"})


class NodeConfigError(ValueError):
    """The ``AGENTFLOW_NODE_*`` environment is internally inconsistent.

    Raised at boot so a misconfigured node fails fast rather than serving a
    half-wired surface: an edge with no center URL to emit to, a node with no
    token to authenticate ingest, or an unknown branch.
    """


@dataclass(frozen=True)
class NodeConfig:
    """Resolved node identity. ``standalone`` carries no branch/url/token —
    it is today's single-node demo, unchanged (a strict superset, N1)."""

    role: NodeRole
    branch: str | None = None
    center_url: str | None = None
    token: str | None = None

    @property
    def is_center(self) -> bool:
        return self.role == "center"

    @property
    def is_edge(self) -> bool:
        return self.role == "edge"

    @property
    def is_standalone(self) -> bool:
        return self.role == "standalone"


def _clean(value: str | None) -> str | None:
    """Trim to ``None`` when unset or whitespace-only."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def resolve_node_config(env: Mapping[str, str] | None = None) -> NodeConfig:
    """Resolve the node role/branch/center-url/token from the environment.

    ``AGENTFLOW_NODE_ROLE`` unset or ``standalone`` yields the unchanged
    single-node demo. ``center`` and ``edge`` are fully validated; any
    inconsistency raises :class:`NodeConfigError`.
    """
    if env is None:
        env = os.environ

    raw_role = (env.get("AGENTFLOW_NODE_ROLE") or "").strip().lower()
    role = raw_role or "standalone"
    if role not in _VALID_ROLES:
        raise NodeConfigError(
            f"AGENTFLOW_NODE_ROLE={raw_role!r} is not one of "
            f"{sorted(_VALID_ROLES)} (unset or empty means standalone)."
        )

    if role == "standalone":
        # Strict superset: stray branch/url/token vars are ignored, never
        # validated, so the current demo Space keeps booting with no new env.
        return NodeConfig(role="standalone")

    branch = (_clean(env.get("AGENTFLOW_NODE_BRANCH")) or "").lower() or None
    center_url = _clean(env.get("AGENTFLOW_NODE_CENTER_URL"))
    # The token is a shared secret compared byte-for-byte on the center; do not
    # mutate its value, only treat whitespace-only as unset.
    token = env.get("AGENTFLOW_NODE_TOKEN")
    if token is not None and token.strip() == "":
        token = None
    if not token:
        raise NodeConfigError(
            f"AGENTFLOW_NODE_TOKEN is required in role={role!r} — the center "
            "accepts ingest with it, an edge sends it — but is unset or empty."
        )
    # n4 (G2 audit): the node token must not equal the public demo API key
    # (``DEMO_API_KEY``, default ``demo-key`` — published in the demo docs).
    # ``node/ingest.py``'s bearer check is already a distinct auth path from
    # the API-key auth middleware, but nothing stopped an operator from
    # *configuring* the same well-known value for both — which would let any
    # public demo caller also authenticate as node-to-node federation. Fail
    # fast at boot instead of silently accepting the collision.
    demo_key = env.get("DEMO_API_KEY", "demo-key")
    if demo_key and token == demo_key:
        raise NodeConfigError(
            "AGENTFLOW_NODE_TOKEN must not equal the public demo API key "
            f"(DEMO_API_KEY={demo_key!r}) — that key is published in the demo "
            "docs, so reusing it as the node token would let any public demo "
            "caller authenticate as node-to-node federation."
        )

    if role == "center":
        # The center does not emit, so AGENTFLOW_NODE_CENTER_URL is ignored.
        if branch is None:
            branch = CENTER_BRANCH
        if branch != CENTER_BRANCH:
            raise NodeConfigError(
                f"center node AGENTFLOW_NODE_BRANCH must be {CENTER_BRANCH!r}, got {branch!r}."
            )
        return NodeConfig(role="center", branch=branch, center_url=None, token=token)

    # role == "edge"
    if branch not in EDGE_BRANCHES:
        raise NodeConfigError(
            "edge node AGENTFLOW_NODE_BRANCH must be one of "
            f"{sorted(EDGE_BRANCHES)}, got {branch!r}."
        )
    if not center_url:
        raise NodeConfigError(
            "AGENTFLOW_NODE_CENTER_URL is required in role='edge' (where to emit "
            "events) but is unset or empty."
        )
    return NodeConfig(role="edge", branch=branch, center_url=center_url, token=token)
