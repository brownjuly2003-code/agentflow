from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, build_auth_middleware
from src.serving.api.rate_limiter import RateLimiter


class FrozenClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePipeline:
    def __init__(self, redis_client: "FakeRedis") -> None:
        self._redis = redis_client
        self._commands: list[tuple[str, tuple, dict]] = []

    def zremrangebyscore(self, key: str, minimum: float, maximum: float) -> "FakePipeline":
        self._commands.append(("zremrangebyscore", (key, minimum, maximum), {}))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> "FakePipeline":
        self._commands.append(("zadd", (key, mapping), {}))
        return self

    def zcard(self, key: str) -> "FakePipeline":
        self._commands.append(("zcard", (key,), {}))
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        self._commands.append(("expire", (key, ttl), {}))
        return self

    def zrange(self, key: str, start: int, stop: int, *, withscores: bool = False) -> "FakePipeline":
        self._commands.append(("zrange", (key, start, stop), {"withscores": withscores}))
        return self

    async def execute(self) -> list[object]:
        if self._redis.raise_on_execute is not None:
            raise self._redis.raise_on_execute
        results = []
        for name, args, kwargs in self._commands:
            method = getattr(self._redis, name)
            results.append(await method(*args, **kwargs))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.expirations: dict[str, int] = {}
        self.raise_on_execute: Exception | None = None

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def zremrangebyscore(self, key: str, minimum: float, maximum: float) -> int:
        members = self.sorted_sets.setdefault(key, {})
        removed = [member for member, score in members.items() if minimum <= score <= maximum]
        for member in removed:
            members.pop(member, None)
        return len(removed)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        members = self.sorted_sets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in members:
                added += 1
            members[member] = score
        return added

    async def zcard(self, key: str) -> int:
        return len(self.sorted_sets.get(key, {}))

    async def expire(self, key: str, ttl: int) -> bool:
        self.expirations[key] = ttl
        return True

    async def zrange(
        self,
        key: str,
        start: int,
        stop: int,
        *,
        withscores: bool = False,
    ) -> list[str] | list[tuple[str, float]]:
        members = sorted(self.sorted_sets.get(key, {}).items(), key=lambda item: item[1])
        if stop == -1:
            sliced = members[start:]
        else:
            sliced = members[start : stop + 1]
        if withscores:
            return sliced
        return [member for member, _ in sliced]


class LoggerSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs) -> None:
        self.warning_calls.append((event, kwargs))


def _write_api_keys(path: Path, rate_limit_rpm: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    {
                        "key": "tenant-order-key",
                        "name": "Order Agent",
                        "tenant": "acme",
                        "rate_limit_rpm": rate_limit_rpm,
                        "allowed_entity_types": None,
                        "created_at": "2026-04-10",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


def _build_app(
    api_keys_path: Path,
    db_path: Path,
    rate_limiter: RateLimiter,
) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        admin_key="admin-secret",
        rate_limiter=rate_limiter,
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())

    @app.get("/v1/metrics/revenue")
    async def revenue():
        return {"metric_name": "revenue", "value": 100.0}

    return app


@pytest.mark.asyncio
async def test_rate_limiter_allows_requests_up_to_limit() -> None:
    clock = FrozenClock(1_000.0)
    limiter = RateLimiter(redis_client=FakeRedis(), time_source=clock)

    first_allowed, first_remaining, first_reset = await limiter.check("tenant:key", 2)
    second_allowed, second_remaining, second_reset = await limiter.check("tenant:key", 2)

    assert first_allowed is True
    assert second_allowed is True
    assert first_remaining == 1
    assert second_remaining == 0
    assert first_reset == 1_060
    assert second_reset == 1_060


@pytest.mark.asyncio
async def test_rate_limiter_blocks_request_over_limit() -> None:
    clock = FrozenClock(1_000.0)
    limiter = RateLimiter(redis_client=FakeRedis(), time_source=clock)

    await limiter.check("tenant:key", 2)
    await limiter.check("tenant:key", 2)
    allowed, remaining, reset_at = await limiter.check("tenant:key", 2)

    assert allowed is False
    assert remaining == 0
    assert reset_at == 1_060


@pytest.mark.asyncio
async def test_rate_limiter_expires_old_requests_in_sliding_window() -> None:
    clock = FrozenClock(1_000.0)
    limiter = RateLimiter(redis_client=FakeRedis(), time_source=clock)

    await limiter.check("tenant:key", 2, window_seconds=60)
    await limiter.check("tenant:key", 2, window_seconds=60)
    clock.advance(61)
    allowed, remaining, reset_at = await limiter.check("tenant:key", 2, window_seconds=60)

    assert allowed is True
    assert remaining == 1
    assert reset_at == 1_121


@pytest.mark.asyncio
async def test_rate_limiter_is_isolated_per_key() -> None:
    clock = FrozenClock(1_000.0)
    limiter = RateLimiter(redis_client=FakeRedis(), time_source=clock)

    await limiter.check("tenant:a", 1)
    blocked, _, _ = await limiter.check("tenant:a", 1)
    other_allowed, other_remaining, _ = await limiter.check("tenant:b", 1)

    assert blocked is False
    assert other_allowed is True
    assert other_remaining == 0


@pytest.mark.asyncio
async def test_rate_limiter_persists_counts_across_instances() -> None:
    clock = FrozenClock(1_000.0)
    redis_client = FakeRedis()
    first = RateLimiter(redis_client=redis_client, time_source=clock)
    second = RateLimiter(redis_client=redis_client, time_source=clock)

    await first.check("tenant:key", 2)
    await first.check("tenant:key", 2)
    allowed, remaining, reset_at = await second.check("tenant:key", 2)

    assert allowed is False
    assert remaining == 0
    assert reset_at == 1_060


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = LoggerSpy()
    redis_client = FakeRedis()
    redis_client.raise_on_execute = RuntimeError("redis down")
    limiter = RateLimiter(redis_client=redis_client, time_source=FrozenClock(1_000.0))

    monkeypatch.setattr("src.serving.api.rate_limiter.logger", logger)

    allowed, remaining, reset_at = await limiter.check("tenant:key", 2)

    assert allowed is True
    assert remaining == 2
    assert reset_at == 1_060
    assert logger.warning_calls == [
        ("rate_limiter_unavailable", {"operation": "check", "error": "redis down"})
    ]


def test_auth_middleware_adds_rate_limit_headers_on_success(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    db_path = tmp_path / "usage.duckdb"
    clock = FrozenClock(1_000.0)
    _write_api_keys(api_keys_path, rate_limit_rpm=2)
    client = TestClient(
        _build_app(
            api_keys_path=api_keys_path,
            db_path=db_path,
            rate_limiter=RateLimiter(redis_client=FakeRedis(), time_source=clock),
        )
    )

    response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "1"
    assert response.headers["X-RateLimit-Reset"] == "1060"


def test_auth_middleware_adds_rate_limit_headers_on_throttle(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    db_path = tmp_path / "usage.duckdb"
    clock = FrozenClock(1_000.0)
    _write_api_keys(api_keys_path, rate_limit_rpm=2)
    client = TestClient(
        _build_app(
            api_keys_path=api_keys_path,
            db_path=db_path,
            rate_limiter=RateLimiter(redis_client=FakeRedis(), time_source=clock),
        )
    )

    client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Reset"] == "1060"


def test_auth_middleware_preserves_counters_across_app_restart(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    db_path = tmp_path / "usage.duckdb"
    clock = FrozenClock(1_000.0)
    redis_client = FakeRedis()
    _write_api_keys(api_keys_path, rate_limit_rpm=2)

    first_client = TestClient(
        _build_app(
            api_keys_path=api_keys_path,
            db_path=db_path,
            rate_limiter=RateLimiter(redis_client=redis_client, time_source=clock),
        )
    )
    second_client = TestClient(
        _build_app(
            api_keys_path=api_keys_path,
            db_path=db_path,
            rate_limiter=RateLimiter(redis_client=redis_client, time_source=clock),
        )
    )

    first_client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    first_client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    response = second_client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 429
