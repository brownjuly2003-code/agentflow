from typing import Literal

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from src.serving.api.auth.manager import tenant_key_allowed_tables
from src.serving.semantic_layer.search_index import SearchHit

logger = structlog.get_logger()
router = APIRouter(tags=["search"])
SEARCH_QUERY = Query(..., min_length=2, description="Natural language search query")
SEARCH_LIMIT = Query(10, ge=1, le=50)
SEARCH_ENTITY_TYPES = Query(None)


class SearchResult(BaseModel):
    type: Literal["entity", "metric", "catalog_field"]
    id: str
    entity_type: str | None
    score: float
    snippet: str
    endpoint: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


def _normalize_entity_types(entity_types: list[str] | None) -> list[str] | None:
    if not entity_types:
        return None

    normalized = []
    seen = set()
    for item in entity_types:
        for part in item.split(","):
            candidate = part.strip().lower()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
    return normalized or None


def _allowed_entity_types(req: Request) -> list[str] | None:
    tenant_key = getattr(req.state, "tenant_key", None)
    if tenant_key is None or getattr(tenant_key, "allowed_entity_types", None) is None:
        return None
    catalog = req.app.state.catalog
    allowed_tables = set(
        tenant_key_allowed_tables(
            tenant_key,
            {name: entity.table for name, entity in catalog.entities.items()},
        )
    )
    return [name for name, entity in catalog.entities.items() if entity.table in allowed_tables]


@router.get("/search", response_model=SearchResponse)
async def search(
    req: Request,
    q: str = SEARCH_QUERY,
    limit: int = SEARCH_LIMIT,
    entity_types: list[str] | None = SEARCH_ENTITY_TYPES,
) -> SearchResponse:
    search_index = req.app.state.search_index
    normalized_entity_types = _normalize_entity_types(entity_types)
    # The key allowlist is authorization, the query filter is a preference. They
    # are passed to the index separately: folding the allowlist into
    # `entity_types` would drop every metric document for a scoped key, because
    # an entity_types filter means "entities only".
    authorized_entity_types = _allowed_entity_types(req)
    if authorized_entity_types is not None and normalized_entity_types is not None:
        narrowed = [t for t in normalized_entity_types if t in set(authorized_entity_types)]
        if not narrowed:
            # Asking only for types this key cannot read is an empty result set,
            # not a 403: /v1/entity already answers 403 for the direct lookup.
            return SearchResponse(query=q, results=[])
        search_entity_types: list[str] | None = narrowed
    else:
        search_entity_types = normalized_entity_types

    hits: list[SearchHit] = search_index.search(
        q,
        limit=limit,
        entity_types=search_entity_types,
        authorized_entity_types=authorized_entity_types,
    )
    if authorized_entity_types is not None:
        # Defense in depth. The index already dropped unauthorized documents
        # before scoring; re-check the serialized hits so a future index change
        # cannot leak one. Hits are mappings — the previous post-filter read
        # them with getattr(), always got None, and passed every forbidden row
        # through (audit_gpt_11_07_26.md P0-4).
        allowed = set(authorized_entity_types)
        hits = [hit for hit in hits if hit["entity_type"] is None or hit["entity_type"] in allowed]
    logger.info(
        "semantic_search_executed",
        query=q,
        results=len(hits),
        entity_types=normalized_entity_types,
    )
    return SearchResponse(query=q, results=[SearchResult(**hit) for hit in hits])
