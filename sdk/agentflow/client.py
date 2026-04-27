import time
from datetime import UTC, datetime
from typing import Any, Iterator, TypeVar, cast
from uuid import uuid4

import httpx
from pydantic import BaseModel

from agentflow.circuit_breaker import CircuitBreaker
from agentflow.exceptions import (
    AgentFlowError,
    AuthError,
    PermissionDeniedError,
    DataFreshnessError,
    EntityNotFoundError,
    RateLimitError,
)
from agentflow.models import (
    CatalogResponse,
    Changelog,
    ContractDiff,
    ContractSummary,
    ContractValidation,
    EntityEnvelope,
    EntityContract,
    HealthStatus,
    Lineage,
    MetricResult,
    OrderEntity,
    ProductEntity,
    QueryExplanation,
    QueryResult,
    SearchResults,
    SessionEntity,
    UserEntity,
)
from agentflow.retry import RETRYABLE_STATUS, RetryPolicy, is_retryable_method

EntityModelT = TypeVar("EntityModelT", bound=BaseModel)


def _normalize_as_of(as_of: datetime | str | None) -> str | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        value = as_of
    else:
        try:
            value = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError:
            return as_of
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


class AgentFlowClient(metaclass=_LegacyResilienceInitCompat):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        contract_version: str | None = None,
        api_version: str | None = None,
    ):
        headers = {"X-API-Key": api_key}
        if api_version is not None:
            headers["X-AgentFlow-Version"] = api_version
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=headers,
        )
        self._contract_versions = self._parse_contract_versions(contract_version)
        self._contract_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_server_version: str | None = None
        self._last_latest_version: str | None = None
        self._last_deprecated: str | None = None
        self._last_deprecation_warning: str | None = None
        self.retry_policy = RetryPolicy()
        self.circuit_breaker = CircuitBreaker()

    @property
    def last_server_version(self) -> str | None:
        return self._last_server_version

    @property
    def last_deprecation_warning(self) -> str | None:
        return self._last_deprecation_warning

    def configure_resilience(
        self,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> "AgentFlowClient":
        if retry_policy is not None:
            self.retry_policy = retry_policy
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        return self

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        can_retry = is_retryable_method(method, headers=headers)
        self.circuit_breaker.before_call()
        while True:
            try:
                response = self._client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=headers,
                )
            except httpx.TransportError as exc:
                if can_retry and attempt < self.retry_policy.max_attempts - 1:
                    delay = self.retry_policy.compute_delay(attempt)
                    attempt += 1
                    time.sleep(delay)
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
                time.sleep(delay)
                continue
            break

        self._record_version_headers(response.headers)

        if response.status_code >= 500:
            self.circuit_breaker.record_failure()
        else:
            self.circuit_breaker.record_success()

        payload = cast(dict[str, Any], response.json())

        if response.status_code == 401:
            detail = payload.get("detail", "Unauthorized")
            raise AuthError(detail)

        if response.status_code == 403:
            detail = payload.get("detail", "Forbidden")
            raise PermissionDeniedError(detail)

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

    def _record_version_headers(self, headers: httpx.Headers) -> None:
        self._last_server_version = headers.get("X-AgentFlow-Version")
        self._last_latest_version = headers.get("X-AgentFlow-Latest-Version")
        self._last_deprecated = headers.get("X-AgentFlow-Deprecated")
        self._last_deprecation_warning = headers.get(
            "X-AgentFlow-Deprecation-Warning"
        )

    def _get_entity(
        self,
        entity_type: str,
        entity_id: str,
        model: type[EntityModelT],
        as_of: datetime | str | None = None,
    ) -> EntityModelT:
        envelope = self.get_entity(entity_type, entity_id, as_of=as_of)
        return cast(
            EntityModelT,
            model.model_validate(envelope.data),
        )

    def _parse_contract_versions(
        self,
        contract_version: str | None,
    ) -> dict[str, str]:
        if contract_version is None:
            return {}
        entity, separator, version = contract_version.partition(":")
        if not separator or not entity or not version:
            raise ValueError(
                "contract_version must use '<entity>:<version>' format."
            )
        return {entity: version[1:] if version.startswith("v") else version}

    def _apply_contract_version(
        self,
        entity_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        version = self._contract_versions.get(entity_type)
        if version is None:
            return payload
        contract = self._get_contract(entity_type, version)
        fields = contract.get("fields", [])
        required_fields = [
            field["name"]
            for field in fields
            if field.get("required")
        ]
        missing_fields = [
            field_name
            for field_name in required_fields
            if field_name not in payload
        ]
        if missing_fields:
            raise AgentFlowError(
                "Contract validation failed. Missing required fields: "
                + ", ".join(missing_fields)
            )
        allowed_fields = {field["name"] for field in fields}
        return {
            name: value
            for name, value in payload.items()
            if name in allowed_fields
        }

    def _get_contract(self, entity_type: str, version: str) -> dict[str, Any]:
        cache_key = (entity_type, version)
        cached = self._contract_cache.get(cache_key)
        if cached is not None:
            return cached
        contract = self._request("GET", f"/v1/contracts/{entity_type}/{version}")
        self._contract_cache[cache_key] = contract
        return contract

    def get_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        as_of: datetime | str | None = None,
    ) -> EntityEnvelope:
        params: dict[str, Any] | None = None
        normalized_as_of = _normalize_as_of(as_of)
        if normalized_as_of is not None:
            params = {"as_of": normalized_as_of}
        payload = self._request(
            "GET",
            f"/v1/entity/{entity_type}/{entity_id}",
            params=params,
        )
        envelope = EntityEnvelope.model_validate(payload)
        return envelope.model_copy(
            update={"data": self._apply_contract_version(entity_type, envelope.data)}
        )

    def get_order(
        self,
        order_id: str,
        *,
        as_of: datetime | str | None = None,
    ) -> OrderEntity:
        return self._get_entity("order", order_id, OrderEntity, as_of=as_of)

    def get_user(
        self,
        user_id: str,
        *,
        as_of: datetime | str | None = None,
    ) -> UserEntity:
        return self._get_entity("user", user_id, UserEntity, as_of=as_of)

    def get_product(
        self,
        product_id: str,
        *,
        as_of: datetime | str | None = None,
    ) -> ProductEntity:
        return self._get_entity("product", product_id, ProductEntity, as_of=as_of)

    def get_session(
        self,
        session_id: str,
        *,
        as_of: datetime | str | None = None,
    ) -> SessionEntity:
        return self._get_entity("session", session_id, SessionEntity, as_of=as_of)

    def get_metric(
        self,
        name: str,
        window: str = "1h",
        *,
        as_of: datetime | str | None = None,
    ) -> MetricResult:
        params: dict[str, Any] = {"window": window}
        normalized_as_of = _normalize_as_of(as_of)
        if normalized_as_of is not None:
            params["as_of"] = normalized_as_of
        payload = self._request("GET", f"/v1/metrics/{name}", params=params)
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

    def _query_page(
        self,
        question: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question}
        if limit is not None:
            payload["limit"] = limit
        if cursor is not None:
            payload["cursor"] = cursor
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        return self._request("POST", "/v1/query", json=payload, headers=headers)

    def query(
        self,
        question: str,
        limit: int | None = None,
        cursor: str | None = None,
        idempotency_key: str | None = None,
    ) -> QueryResult:
        payload = self._query_page(
            question,
            limit=limit,
            cursor=cursor,
            idempotency_key=idempotency_key,
        )
        return QueryResult.model_validate(self._normalize_query_payload(payload))

    def explain_query(
        self,
        question: str,
        contract_version: str | None = None,
    ) -> QueryExplanation:
        payload: dict[str, Any] = {"question": question}
        if contract_version is not None:
            payload["contract_version"] = contract_version
        response = self._request("POST", "/v1/query/explain", json=payload)
        return QueryExplanation.model_validate(response)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        entity_types: list[str] | None = None,
    ) -> SearchResults:
        params: dict[str, Any] = {"q": query, "limit": limit}
        if entity_types is not None:
            params["entity_types"] = entity_types
        payload = self._request("GET", "/v1/search", params=params)
        return SearchResults.model_validate(payload)

    def list_contracts(self) -> list[ContractSummary]:
        payload = self._request("GET", "/v1/contracts")
        return [
            ContractSummary.model_validate(contract)
            for contract in payload.get("contracts", [])
        ]

    def get_contract(
        self,
        entity: str,
        version: str | None = None,
    ) -> EntityContract:
        path = f"/v1/contracts/{entity}"
        if version is not None:
            path = f"{path}/{version}"
        payload = self._request("GET", path)
        return EntityContract.model_validate(payload)

    def diff_contracts(
        self,
        entity: str,
        from_version: str,
        to_version: str,
    ) -> ContractDiff:
        payload = self._request(
            "GET",
            f"/v1/contracts/{entity}/diff/{from_version}/{to_version}",
        )
        return ContractDiff.model_validate(payload)

    def validate_contract(
        self,
        entity: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> ContractValidation:
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        response = self._request(
            "POST",
            f"/v1/contracts/{entity}/validate",
            json=payload,
            headers=headers,
        )
        return ContractValidation.model_validate(response)

    def get_lineage(self, entity_type: str, entity_id: str) -> Lineage:
        payload = self._request("GET", f"/v1/lineage/{entity_type}/{entity_id}")
        return Lineage.model_validate(payload)

    def get_changelog(self) -> Changelog:
        payload = self._request("GET", "/v1/changelog")
        return Changelog.model_validate(payload)

    def paginate(
        self,
        question: str,
        page_size: int = 100,
    ) -> Iterator[list[dict[str, Any]]]:
        cursor: str | None = None
        while True:
            payload = self._query_page(question, limit=page_size, cursor=cursor)
            rows = cast(list[dict[str, Any]], payload.get("rows", payload.get("answer", [])))
            yield rows
            if not payload.get("has_more"):
                break
            cursor = cast(str | None, payload.get("next_cursor"))
            if cursor is None:
                break

    def health(self) -> HealthStatus:
        payload = self._request("GET", "/v1/health")
        return HealthStatus.model_validate(payload)

    def is_fresh(self, max_age_seconds: int = 60) -> bool:
        health = self.health()
        if health.status != "healthy":
            raise DataFreshnessError(
                f"Pipeline is {health.status}; freshness check cannot be trusted"
            )
        if health.freshness_seconds is None:
            raise DataFreshnessError("Pipeline freshness metric is unavailable")
        return health.freshness_seconds < max_age_seconds

    def catalog(self) -> CatalogResponse:
        payload = self._request("GET", "/v1/catalog")
        return CatalogResponse.model_validate(payload)

    def batch(
        self,
        requests: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = (
            {"Idempotency-Key": idempotency_key}
            if idempotency_key is not None
            else None
        )
        return self._request(
            "POST",
            "/v1/batch",
            json={"requests": requests},
            headers=headers,
        )

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
