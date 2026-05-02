"""Redis-backed query cache with graceful fallback."""

import inspect
import json
from datetime import timedelta
from typing import Any, cast

import structlog
from fastapi.encoders import jsonable_encoder

logger = structlog.get_logger()
ENTITY_TTL_SECONDS = 5

try:
    import redis.asyncio as redis  # type: ignore[import-untyped,unused-ignore]
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]


class QueryCache:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_client=None,
    ):
        self._redis = redis_client
        if self._redis is None and redis is not None:
            self._redis = redis.from_url(redis_url)

    async def get(self, key: str) -> dict | None:
        if self._redis is None:
            logger.warning(
                "query_cache_unavailable",
                operation="get",
                error="redis package not installed",
            )
            return None
        try:
            data = await self._redis.get(key)
        except Exception as exc:
            logger.warning(
                "query_cache_unavailable",
                operation="get",
                error=str(exc),
            )
            return None
        if not data:
            return None
        if isinstance(data, bytes):
            data = data.decode()
        try:
            return cast(dict[Any, Any], json.loads(data))
        except json.JSONDecodeError as exc:
            logger.warning(
                "query_cache_corrupt",
                operation="get",
                key=key,
                error=str(exc),
            )
            return None

    async def set(self, key: str, value: dict, ttl: int = 30) -> None:
        if self._redis is None:
            logger.warning(
                "query_cache_unavailable",
                operation="set",
                error="redis package not installed",
            )
            return
        try:
            await self._redis.setex(
                key,
                timedelta(seconds=ttl),
                json.dumps(jsonable_encoder(value)),
            )
        except Exception as exc:
            logger.warning(
                "query_cache_unavailable",
                operation="set",
                error=str(exc),
            )

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        if self._redis is None:
            logger.warning(
                "query_cache_unavailable",
                operation="delete",
                error="redis package not installed",
            )
            return
        try:
            await self._redis.delete(*keys)
        except Exception as exc:
            logger.warning(
                "query_cache_unavailable",
                operation="delete",
                error=str(exc),
            )

    async def invalidate_metrics(self) -> None:
        if self._redis is None:
            logger.warning(
                "query_cache_unavailable",
                operation="invalidate",
                error="redis package not installed",
            )
            return
        try:
            keys = await self._redis.keys("metric:*")
        except Exception as exc:
            logger.warning(
                "query_cache_unavailable",
                operation="invalidate",
                error=str(exc),
            )
            return
        normalized_keys = [key.decode() if isinstance(key, bytes) else key for key in keys]
        if normalized_keys:
            await self._redis.delete(*normalized_keys)

    async def close(self) -> None:
        if self._redis is None:
            return
        close = getattr(self._redis, "aclose", None)
        if close is not None:
            try:
                await close()
            except RuntimeError as exc:
                if "Event loop is closed" not in str(exc):
                    raise
            return
        close = getattr(self._redis, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            try:
                await result
            except RuntimeError as exc:
                if "Event loop is closed" not in str(exc):
                    raise

    @staticmethod
    def metric_key(
        name: str,
        window: str,
        as_of: str | None = None,
        *,
        tenant: str | None = None,
        version: str | None = None,
    ) -> str:
        parts = ["metric"]
        if tenant is not None:
            parts.append(f"tenant={tenant}")
        if version is not None:
            parts.append(f"version={version}")
        parts.extend([name, window, as_of or "now"])
        return ":".join(parts)


def cache_entity_key(
    tenant_id: str | None,
    entity_type: str,
    entity_id: str,
) -> str:
    tenant = tenant_id or "default"
    return f"entity:{tenant}:{entity_type}:{entity_id}"


async def invalidate_entity(
    cache: QueryCache,
    tenant_id: str | None,
    entity_type: str,
    entity_id: str,
) -> None:
    await cache.delete(cache_entity_key(tenant_id, entity_type, entity_id))
