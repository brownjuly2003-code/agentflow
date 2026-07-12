"""Which tenant an ingested event belongs to.

A leaf module on purpose. Both the pipeline (which journals the tenant) and the
ClickHouse sink (which now stamps it onto every serving row — audit P0-1) need
one answer to this question, and the sink cannot import the pipeline: the
pipeline already imports the sink.
"""

from __future__ import annotations

from src.tenancy import DEFAULT_TENANT

__all__ = ["DEFAULT_TENANT", "event_tenant"]


def event_tenant(event: dict) -> str:
    """The tenant that owns ``event`` — never empty."""
    source_metadata = event.get("source_metadata", {})
    metadata_tenant = source_metadata.get("tenant") if isinstance(source_metadata, dict) else None
    tenant = event.get("tenant") or metadata_tenant
    return str(tenant) if tenant else DEFAULT_TENANT
