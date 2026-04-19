from typing import Literal

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

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


@router.get("/search", response_model=SearchResponse)
async def search(
    req: Request,
    q: str = SEARCH_QUERY,
    limit: int = SEARCH_LIMIT,
    entity_types: list[str] | None = SEARCH_ENTITY_TYPES,
):
    search_index = req.app.state.search_index
    normalized_entity_types = _normalize_entity_types(entity_types)
    results = search_index.search(
        q,
        limit=limit,
        entity_types=normalized_entity_types,
    )
    logger.info(
        "semantic_search_executed",
        query=q,
        results=len(results),
        entity_types=normalized_entity_types,
    )
    return SearchResponse(query=q, results=results)
