from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import JSONResponse

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


def default_api_versions_path() -> Path:
    return Path(os.getenv("AGENTFLOW_API_VERSIONS_FILE", "config/api_versions.yaml"))


def default_tenants_path() -> Path:
    return Path(os.getenv("AGENTFLOW_TENANTS_FILE", "config/tenants.yaml"))


@dataclass(frozen=True)
class ApiChange:
    type: str
    description: str


@dataclass(frozen=True)
class ApiVersion:
    date: str
    status: str
    changes: tuple[ApiChange, ...]

    @property
    def parsed_date(self) -> date_type:
        return date_type.fromisoformat(self.date)


class ApiVersionRegistry:
    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = (
            Path(config_path) if config_path is not None else default_api_versions_path()
        )
        self._versions = self._load_versions()
        self._by_date = {version.date: version for version in self._versions}

    def all(self) -> list[ApiVersion]:
        return list(self._versions)

    def get(self, version_date: str) -> ApiVersion:
        try:
            return self._by_date[version_date]
        except KeyError as exc:
            raise ValueError(f"Unsupported API version: {version_date}") from exc

    def latest(self) -> ApiVersion:
        for version in self._versions:
            if version.status == "latest":
                return version
        return self._versions[-1]

    def changes_between(self, older_version: str, newer_version: str) -> list[ApiChange]:
        if older_version == newer_version:
            return []
        older_index = self._index_of(older_version)
        newer_index = self._index_of(newer_version)
        if older_index > newer_index:
            return []
        changes: list[ApiChange] = []
        for version in self._versions[older_index + 1 : newer_index + 1]:
            changes.extend(version.changes)
        return changes

    def is_deprecated(self, version_date: str) -> bool:
        version = self.get(version_date)
        if version.status == "deprecated":
            return True
        return (self.latest().parsed_date - version.parsed_date).days > 183

    def deprecation_warning(self, version_date: str) -> str | None:
        if not self.is_deprecated(version_date):
            return None
        unsupported_after = _add_one_year(self.get(version_date).parsed_date).isoformat()
        return (
            f"Your pinned version {version_date} will be unsupported after "
            f"{unsupported_after}. See /v1/changelog."
        )

    def changelog(self) -> dict:
        return {
            "latest_version": self.latest().date,
            "versions": [
                {
                    "date": version.date,
                    "status": version.status,
                    "changes": [change.description for change in version.changes],
                }
                for version in self._versions
            ],
        }

    def _index_of(self, version_date: str) -> int:
        self.get(version_date)
        for index, version in enumerate(self._versions):
            if version.date == version_date:
                return index
        raise ValueError(f"Unsupported API version: {version_date}")

    def _load_versions(self) -> list[ApiVersion]:
        if not self.config_path.exists():
            return [
                ApiVersion(
                    date="2026-04-11",
                    status="latest",
                    changes=(),
                )
            ]

        raw = self.config_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(raw) or {}
        else:  # pragma: no cover
            data = json.loads(raw)

        versions = [
            ApiVersion(
                date=item["date"],
                status=item["status"],
                changes=tuple(
                    ApiChange(
                        type=change["type"],
                        description=change["description"],
                    )
                    for change in item.get("changes", [])
                ),
            )
            for item in data.get("versions", [])
        ]
        if not versions:
            raise ValueError(f"No API versions configured in {self.config_path}.")
        return sorted(versions, key=lambda version: version.parsed_date)


class ResponseTransformer:
    def __init__(self, registry: ApiVersionRegistry) -> None:
        self.registry = registry

    def transform(self, response: dict, from_version: str, to_version: str) -> dict:
        if from_version == to_version:
            return copy.deepcopy(response)
        transformed = copy.deepcopy(response)
        for change in reversed(self.registry.changes_between(to_version, from_version)):
            transformed = self._apply_inverse(transformed, change)
        return transformed

    def transform_headers(
        self,
        headers: Mapping[str, str],
        from_version: str,
        to_version: str,
    ) -> dict[str, str]:
        transformed = dict(headers)
        if from_version == to_version:
            return transformed
        for change in reversed(self.registry.changes_between(to_version, from_version)):
            self._apply_header_inverse(transformed, change)
        return transformed

    def _apply_inverse(self, response: dict, change: ApiChange) -> dict:
        field_path = self._added_field_path(change.description)
        if field_path is not None:
            self._pop_field_path(response, field_path.split("."))
        return response

    def _apply_header_inverse(self, headers: dict[str, str], change: ApiChange) -> None:
        header_name = self._added_header_name(change.description)
        if header_name is not None:
            self._pop_header(headers, header_name)

    def _pop_header(self, headers: dict[str, str], name: str) -> None:
        for key in list(headers):
            if key.lower() == name.lower():
                headers.pop(key, None)

    def _added_field_path(self, description: str) -> str | None:
        match = re.match(r"^Added ([A-Za-z0-9_.-]+) to ", description)
        if match is None:
            return None
        return match.group(1)

    def _added_header_name(self, description: str) -> str | None:
        match = re.match(r"^Added ([A-Za-z0-9-]+) response header$", description)
        if match is None:
            return None
        return match.group(1)

    def _pop_field_path(self, payload: dict, path_parts: list[str]) -> None:
        current = payload
        for part in path_parts[:-1]:
            next_value = current.get(part)
            if not isinstance(next_value, dict):
                return
            current = next_value
        current.pop(path_parts[-1], None)


def get_version_registry(request: Request) -> ApiVersionRegistry:
    registry = getattr(request.app.state, "version_registry", None)
    if registry is None:
        registry = ApiVersionRegistry()
        request.app.state.version_registry = registry
    return registry


def get_response_transformer(request: Request) -> ResponseTransformer:
    transformer = getattr(request.app.state, "response_transformer", None)
    if transformer is None:
        transformer = ResponseTransformer(get_version_registry(request))
        request.app.state.response_transformer = transformer
    return transformer


def resolve_request_version(request: Request) -> str:
    cached = getattr(request.state, "agentflow_version", None)
    if isinstance(cached, str) and cached:
        return cached

    registry = get_version_registry(request)
    requested = request.headers.get("X-AgentFlow-Version")
    if requested:
        registry.get(requested)
        request.state.agentflow_version = requested
        return requested

    tenant_id_value = getattr(request.state, "tenant_id", None)
    tenant_id = str(tenant_id_value) if tenant_id_value is not None else None
    if tenant_id is None:
        tenant_key = getattr(request.state, "tenant_key", None)
        tenant_value = getattr(tenant_key, "tenant", None)
        tenant_id = str(tenant_value) if tenant_value is not None else None

    pinned = _load_tenant_version_pins().get(tenant_id) if tenant_id is not None else None
    if pinned:
        registry.get(pinned)
        request.state.agentflow_version = pinned
        return pinned

    latest = registry.latest().date
    request.state.agentflow_version = latest
    return latest


def build_versioning_middleware():
    async def versioning(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        registry = get_version_registry(request)
        requested = request.headers.get("X-AgentFlow-Version")
        if requested:
            try:
                registry.get(requested)
            except ValueError as exc:
                return JSONResponse(status_code=400, content={"detail": str(exc)})

        response = await call_next(request)
        try:
            resolved_version = resolve_request_version(request)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        latest_version = registry.latest().date
        response.headers["X-AgentFlow-Version"] = resolved_version
        response.headers["X-AgentFlow-Latest-Version"] = latest_version
        response.headers["X-AgentFlow-Deprecated"] = (
            "true" if registry.is_deprecated(resolved_version) else "false"
        )
        warning = registry.deprecation_warning(resolved_version)
        if warning is not None:
            response.headers["X-AgentFlow-Deprecation-Warning"] = warning

        transformer = get_response_transformer(request)
        transformed_headers = transformer.transform_headers(
            response.headers,
            from_version=latest_version,
            to_version=resolved_version,
        )
        for key in list(response.headers.keys()):
            if key not in transformed_headers:
                del response.headers[key]
        for key, value in transformed_headers.items():
            response.headers[key] = value
        return response

    return versioning


def _load_tenant_version_pins(config_path: Path | str | None = None) -> dict[str, str]:
    path = Path(config_path) if config_path is not None else default_tenants_path()
    if not path.exists():
        return {}

    raw = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(raw) or {}
    else:  # pragma: no cover
        data = json.loads(raw)

    pins: dict[str, str] = {}
    for tenant in data.get("tenants", []):
        tenant_id = tenant.get("id")
        pinned = tenant.get("api_version_pin")
        if tenant_id and pinned:
            pins[str(tenant_id)] = str(pinned)
    return pins


def _add_one_year(value: date_type) -> date_type:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + 1)
