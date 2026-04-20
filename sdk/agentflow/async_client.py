import asyncio
from typing import Any, AsyncIterator, TypeVar, cast
from uuid import uuid4

import httpx
from pydantic import BaseModel

from agentflow.circuit_breaker import CircuitBreaker
from agentflow.exceptions import (
    AgentFlowError,
    AuthError,
    DataFreshnessError,
    EntityNotFoundError,
    RateLimitError,
)
from agentflow.models import (
    CatalogResponse,
    EntityEnvelope,
    HealthStatus,
    MetricResult,
    OrderEntity,
    ProductEntity,
    QueryResult,
    SessionEntity,
    UserEntity,
)
from agentflow.retry import RETRYABLE_STATUS, RetryPolicy, is_retryable_method

EntityModelT = TypeVar("EntityModelT", bound=BaseModel)


class _LegacyResilienceInitCompat(type):
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        retry_policy = kwargs.pop("retry_policy", None)
        circuit_breaker = kwargs.pop("circuit_breaker", None)
        client = super().__call__(*args, **kwargs)
        if retry_policy is not None or circuit_breaker is not None:
            client.configure_resilience(
                retry_policy=retry_policy,
                circuit_breaker=circuit_breaker,
            )
        return client


class AsyncAgentFlowClient(metaclass=_LegacyResilienceInitCompat):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"X-API-Key": api_key},
        )
        self.retry_policy = RetryPolicy()
        self.circuit_breaker = CircuitBreaker()

    def configure_resilience(
        self,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> "AsyncAgentFlowClient":
        if retry_policy is not None:
            self.retry_policy = retry_policy
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        return self

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        can_retry = is_retryable_method(method)
        self.circuit_breaker.before_call()
        while True:
            try:
                response = await self._http.request(method, path, params=params, json=json)
            except httpx.TransportError as exc:
                if can_retry and attempt < self.retry_policy.max_attempts - 1:
                    delay = self.retry_policy.compute_delay(attempt)
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
                self.circuit_breaker.record_failure()
                raise AgentFlowError(f"Request failed: {exc}") from exc
            retry_after: float | None = None
            retry_after_header = response.headers.get("Retry-After")
            if retry_after_header is not None:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    retry_after = None
            if (
                can_retry
                and response.status_code in RETRYABLE_STATUS
                and attempt < self.retry_policy.max_attempts - 1
            ):
                delay = self.retry_policy.compute_delay(attempt, retry_after)
                attempt += 1
                await asyncio.sleep(delay)
                continue
            break

        if response.status_code >= 500:
            self.circuit_breaker.record_failure()
        else:
            self.circuit_breaker.record_success()

        payload = cast(dict[str, Any], response.json())

        if response.status_code == 401:
            detail = payload.get("detail", "Unauthorized")
            raise AuthError(detail)

        if response.status_code == 429:
            detail = payload.get("detail", "Rate limit exceeded")
            retry_after = int(response.headers.get("Retry-After", "0"))
            raise RateLimitError(detail, retry_after=retry_after)

        if response.status_code == 404:
            detail = payload.get("detail", "Resource not found")
            parts = path.strip("/").split("/")
            if len(parts) >= 4 and parts[1] == "entity":
                raise EntityNotFoundError(parts[2], parts[3], detail)
            raise AgentFlowError(detail)

        if response.status_code >= 400:
            detail = payload.get("detail", response.text)
            raise AgentFlowError(detail)

        return payload

    async def _get_entity(
        self,
        entity_type: str,
        entity_id: str,
        model: type[EntityModelT],
    ) -> EntityModelT:
        payload = await self._request("GET", f"/v1/entity/{entity_type}/{entity_id}")
        envelope = EntityEnvelope.model_validate(payload)
        return cast(EntityModelT, model.model_validate(envelope.data))

    async def get_order(self, order_id: str) -> OrderEntity:
        return await self._get_entity("order", order_id, OrderEntity)

    async def get_user(self, user_id: str) -> UserEntity:
        return await self._get_entity("user", user_id, UserEntity)

    async def get_product(self, product_id: str) -> ProductEntity:
        return await self._get_entity("product", product_id, ProductEntity)

    async def get_session(self, session_id: str) -> SessionEntity:
        return await self._get_entity("session", session_id, SessionEntity)

    async def get_metric(self, name: str, window: str = "1h") -> MetricResult:
        payload = await self._request("GET", f"/v1/metrics/{name}", params={"window": window})
        return MetricResult.model_validate(payload)

    def _normalize_query_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(payload.get("metadata", {}))
        for key in ("total_count", "next_cursor", "has_more", "page_size"):
            if key in payload:
                metadata[key] = payload[key]
        return {
            "answer": payload.get("answer", payload.get("rows", [])),
            "sql": payload.get("sql"),
            "metadata": metadata,
        }

    async def _query_page(
        self,
        question: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if limit is not None:
            payload["limit"] = limit
        if cursor is not None:
            payload["cursor"] = cursor
        return await self._request("POST", "/v1/query", json=payload)

    async def query(
        self,
        question: str,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> QueryResult:
        payload = await self._query_page(question, limit=limit, cursor=cursor)
        return QueryResult.model_validate(self._normalize_query_payload(payload))

    async def paginate(
        self,
        question: str,
        page_size: int = 100,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        cursor: str | None = None
        while True:
            payload = await self._query_page(question, limit=page_size, cursor=cursor)
            rows = cast(list[dict[str, Any]], payload.get("rows", payload.get("answer", [])))
            yield rows
            if not payload.get("has_more"):
                break
            cursor = cast(str | None, payload.get("next_cursor"))
            if cursor is None:
                break

    async def health(self) -> HealthStatus:
        payload = await self._request("GET", "/v1/health")
        return HealthStatus.model_validate(payload)

    async def is_fresh(self, max_age_seconds: int = 60) -> bool:
        health = await self.health()
        if health.status != "healthy":
            raise DataFreshnessError(
                f"Pipeline is {health.status}; freshness check cannot be trusted"
            )
        if health.freshness_seconds is None:
            raise DataFreshnessError("Pipeline freshness metric is unavailable")
        return health.freshness_seconds < max_age_seconds

    async def catalog(self) -> CatalogResponse:
        payload = await self._request("GET", "/v1/catalog")
        return CatalogResponse.model_validate(payload)

    async def batch(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", "/v1/batch", json={"requests": requests})

    def batch_entity(
        self,
        entity_type: str,
        entity_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": request_id or f"entity-{uuid4().hex[:8]}",
            "type": "entity",
            "params": {
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        }

    def batch_metric(
        self,
        name: str,
        window: str = "1h",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": request_id or f"metric-{uuid4().hex[:8]}",
            "type": "metric",
            "params": {
                "name": name,
                "window": window,
            },
        }

    def batch_query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"question": question}
        if context is not None:
            params["context"] = context
        return {
            "id": request_id or f"query-{uuid4().hex[:8]}",
            "type": "query",
            "params": params,
        }

    async def __aenter__(self) -> "AsyncAgentFlowClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._http.aclose()
