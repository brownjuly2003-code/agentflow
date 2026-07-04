"""Three-node demo topology (ADR 0012) — node role/branch seam.

One image, three roles (``center`` / ``edge`` / ``standalone``) differentiated
purely by environment. This package resolves and validates that environment
once at boot; the center ingest endpoint, the edge emitter, and the
branch-scoped seed all read the resolved :class:`NodeConfig` from
``app.state`` rather than re-reading ``os.environ``.

See ``docs/three-node-demo-topology.md`` for the build contract.
"""

from src.serving.node.config import (
    CENTER_BRANCH,
    EDGE_BRANCHES,
    KNOWN_BRANCHES,
    NodeConfig,
    NodeConfigError,
    NodeRole,
    resolve_node_config,
)

__all__ = [
    "CENTER_BRANCH",
    "EDGE_BRANCHES",
    "KNOWN_BRANCHES",
    "NodeConfig",
    "NodeConfigError",
    "NodeRole",
    "resolve_node_config",
]
