from typing import Literal

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from src.serving.api.auth.manager import tenant_key_allowed_tables

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
):
    search_index = req.app.state.search_index
    normalized_entity_types = _normalize_entity_types(entity_types)
    allowed_entity_types = _allowed_entity_types(req)
    if allowed_entity_types is not None:
        allowed = set(allowed_entity_types)
        if normalized_entity_types is None:
            # Caller did not request a filter — let SearchIndex.search() return
            # both metric and entity matches, then drop entity rows that are
            # outside the key allowlist below. Treating the allowlist as an
            # entity_types filter would silently exclude every metric document
            # for scoped keys (Codex review P2 on /v1/search).
            search_entity_types: list[str] | None = None
        else:
            search_entity_types = [t for t in normalized_entity_types if t in allowed]
            if not search_entity_types:
                return SearchResponse(query=q, results=[])
    else:
        search_entity_types = normalized_entity_types
    results = search_index.search(
        q,
        limit=limit,
        entity_types=search_entity_types,
    )
    if allowed_entity_types is not None and normalized_entity_types is None:
        allowed = set(allowed_entity_types)
        results = [
            result
            for result in results
            if getattr(result, "entity_type", None) is None or result.entity_type in allowed
        ]
    logger.info(
        "semantic_search_executed",
        query=q,
        results=len(results),
        entity_types=normalized_entity_types,
    )
    return SearchResponse(query=q, results=results)
