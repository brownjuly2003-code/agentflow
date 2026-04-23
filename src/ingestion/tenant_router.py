from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


def default_tenants_config_path() -> Path:
    return Path(os.getenv("AGENTFLOW_TENANTS_FILE", "config/tenants.yaml"))


class TenantDefinition(BaseModel):
    id: str
    display_name: str
    kafka_topic_prefix: str
    duckdb_schema: str
    max_events_per_day: int
    max_api_keys: int
    allowed_entity_types: list[str] | None = None


class TenantsConfig(BaseModel):
    tenants: list[TenantDefinition] = Field(default_factory=list)


class TenantRouter:
    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = (
            Path(config_path) if config_path is not None else default_tenants_config_path()
        )

    def has_config(self) -> bool:
        return self.config_path.exists()

    def load(self) -> TenantsConfig:
        if not self.config_path.exists():
            return TenantsConfig()

        raw = self.config_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(raw) or {}
        else:  # pragma: no cover
            data = json.loads(raw)
        return TenantsConfig.model_validate(data)

    def get_tenant(self, tenant_id: str | None) -> TenantDefinition | None:
        if tenant_id is None:
            return None
        for tenant in self.load().tenants:
            if tenant.id == tenant_id:
                return tenant
        return None

    def get_duckdb_schema(self, tenant_id: str | None) -> str | None:
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return None
        return tenant.duckdb_schema

    def route_topic(self, topic: str, tenant_id: str | None) -> str:
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return topic
        return f"{tenant.kafka_topic_prefix}.{topic}"
