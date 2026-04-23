from __future__ import annotations

import time
from collections import defaultdict
from uuid import uuid4

import structlog

from src.constants import DEFAULT_RATE_LIMIT_WINDOW_SECONDS

logger = structlog.get_logger()

try:
    import redis.asyncio as redis  # type: ignore[import-untyped,unused-ignore]
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]


REDIS_WINDOW_EXPIRY_MULTIPLIER = 2


class RateLimiter:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_client=None,
        time_source=time.time,
    ) -> None:
        self._redis = redis_client
        if self._redis is None and redis is not None:
            self._redis = redis.from_url(redis_url)
        self._time_source = time_source
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    ) -> tuple[bool, int, int]:
        now = self._time_source()
        reset_at = int(now + window_seconds)
        if self._redis is None:
            cutoff = now - window_seconds
            window = [stamp for stamp in self._windows[key] if stamp > cutoff]
            self._windows[key] = window
            if len(window) >= limit:
                if window:
                    reset_at = int(window[0] + window_seconds)
                return False, 0, reset_at
            window.append(now)
            reset_at = int(window[0] + window_seconds)
            return True, max(0, limit - len(window)), reset_at

        try:
            pipeline = self._redis.pipeline()
            pipeline.zremrangebyscore(key, float("-inf"), now - window_seconds)
            pipeline.zadd(key, {f"{now}:{uuid4().hex}": now})
            pipeline.zcard(key)
            pipeline.expire(key, window_seconds * REDIS_WINDOW_EXPIRY_MULTIPLIER)
            pipeline.zrange(key, 0, 0, withscores=True)
            results = await pipeline.execute()
        except Exception as exc:
            logger.warning(
                "rate_limiter_unavailable",
                operation="check",
                error=str(exc),
            )
            return True, limit, reset_at

        count = int(results[2])
        oldest_entry = results[4]
        if oldest_entry:
            reset_at = int(float(oldest_entry[0][1]) + window_seconds)
        remaining = max(0, limit - count)
        return count <= limit, remaining, reset_at
