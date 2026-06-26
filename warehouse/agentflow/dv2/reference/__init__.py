"""AgentFlow DV2 supplier / product reference.

A real, reproducible grocery reference (suppliers, products, GS1 marking
codes, sourcing) that fills the catalog / tnved / marking slots the
transactional X5 feed leaves empty, and is published to cloud object storage
(a Hugging Face Dataset) as the project's genuine cloud component.

Public API:
    build_reference  -> deterministic reference tables
    map_reference    -> DV2 raw-vault rows (join-compatible hash keys)
"""

from __future__ import annotations

from .generator import ReferenceTables, build_reference
from .vault_mapping import map_reference

__all__ = ["ReferenceTables", "build_reference", "map_reference"]
