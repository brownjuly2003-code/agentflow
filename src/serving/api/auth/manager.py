from __future__ import annotations

import json
import os
import secrets
import signal
import threading
import time
from collections import defaultdict
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from fastapi import Request
from pydantic import BaseModel, Field, model_validator

from src.constants import (
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    DEFAULT_ROTATION_GRACE_PERIOD_SECONDS,
    FAILED_AUTH_WINDOW_SECONDS,
)

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

from src.serving.api.rate_limiter import RateLimiter
from src.serving.api.security import (
    DEFAULT_SECURITY_CONFIG_PATH,
    load_security_policy,
    verify_api_key,
)

if TYPE_CHECKING:
    from .key_rotation import KeyRotator


DEFAULT_API_KEYS_FILE = os.getenv("AGENTFLOW_API_KEYS_FILE")
DEFAULT_RATE_LIMIT_RPM = int(os.getenv("AGENTFLOW_RATE_LIMIT_RPM", "120"))
DEFAULT_USAGE_DB_PATH = Path(os.getenv("AGENTFLOW_USAGE_DB_PATH", "agentflow_api.duckdb"))
_CURRENT_TENANT_ID: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)


class TenantKey(BaseModel):
    key_id: str | None = None
    key: str | None = None
    key_hash: str | None = None
    previous_key_hash: str | None = None
    previous_key_active_until: datetime | None = None
    name: str
    tenant: str
    rate_limit_rpm: int = Field(default=DEFAULT_RATE_LIMIT_RPM, ge=1)
    allowed_entity_types: list[str] | None = None
    created_at: date
    matched_slot: str = Field(default="current", exclude=True)

    @model_validator(mode="after")
    def validate_key_material(self) -> TenantKey:
        if self.key is None and self.key_hash is None:
            raise ValueError("Either key or key_hash must be provided.")
        return self


class ApiKeysConfig(BaseModel):
    keys: list[TenantKey] = Field(default_factory=list)


class KeyCreateRequest(BaseModel):
    name: str
    tenant: str
    rate_limit_rpm: int = Field(default=DEFAULT_RATE_LIMIT_RPM, ge=1)
    allowed_entity_types: list[str] | None = None


def get_current_tenant_id(default: str | None = None) -> str | None:
    tenant_id = _CURRENT_TENANT_ID.get()
    return tenant_id if tenant_id is not None else default


def tenant_key_allowed_tables(
    tenant_key: TenantKey | None,
    all_catalog_tables: Mapping[str, str] | list[str],
) -> list[str]:
    if isinstance(all_catalog_tables, Mapping):
        table_items = list(all_catalog_tables.items())
    else:
        table_items = [(table, table) for table in all_catalog_tables]
    allowed_entity_types = getattr(tenant_key, "allowed_entity_types", None)
    if tenant_key is None or allowed_entity_types is None:
        return [table for _, table in table_items]
    allowed = set(allowed_entity_types)
    return [
        table
        for entity_type, table in table_items
        if entity_type in allowed or table in allowed
    ]


class AuthManager:
    def __init__(
        self,
        api_keys_path: Path | str | None = DEFAULT_API_KEYS_FILE,
        db_path: Path | str = DEFAULT_USAGE_DB_PATH,
        admin_key: str | None = None,
        security_config_path: Path | str = DEFAULT_SECURITY_CONFIG_PATH,
        time_source=time.monotonic,
        rate_limiter: RateLimiter | None = None,
        redis_url: str | None = None,
    ) -> None:
        self.api_keys_path = Path(api_keys_path) if api_keys_path else None
        resolved_db_path = Path(db_path)
        if (
            os.getenv("AGENTFLOW_USAGE_DB_PATH") is None
            and str(resolved_db_path) == "agentflow_api.duckdb"
        ):
            pipeline_db_path = os.getenv("DUCKDB_PATH")
            if pipeline_db_path:
                pipeline_path = Path(pipeline_db_path)
                suffix = pipeline_path.suffix or ".duckdb"
                resolved_db_path = pipeline_path.with_name(f"{pipeline_path.stem}_api{suffix}")
        self.db_path = resolved_db_path
        self.admin_key = admin_key if admin_key is not None else os.getenv("AGENTFLOW_ADMIN_KEY")
        self.security_config_path = Path(security_config_path)
        self.security_policy = load_security_policy(self.security_config_path)
        self.time_source = time_source
        self.keys_by_value: dict[str, TenantKey] = {}
        self._keys_by_id: dict[str, TenantKey] = {}
        self._hashed_keys: list[TenantKey] = []
        self._loaded_keys: list[TenantKey] = []
        self._runtime_plaintext_by_hash: dict[str, str] = {}
        self._rate_windows: dict[str, list[float]] = defaultdict(list)
        self._failed_auth_windows: dict[str, list[float]] = defaultdict(list)
        self._config_lock = threading.RLock()
        self._rotation_cleanup_timers: dict[str, threading.Timer] = {}
        try:
            self.rotation_grace_period_seconds = max(
                1,
                int(
                    os.getenv(
                        "AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS",
                        str(DEFAULT_ROTATION_GRACE_PERIOD_SECONDS),
                    )
                ),
            )
        except ValueError:
            from src.serving.api import auth as auth_package

            self.rotation_grace_period_seconds = DEFAULT_ROTATION_GRACE_PERIOD_SECONDS
            auth_package.logger.warning(
                "invalid_rotation_grace_period_seconds",
                value=os.getenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS"),
                fallback=DEFAULT_ROTATION_GRACE_PERIOD_SECONDS,
            )
        resolved_redis_url = redis_url or os.getenv("REDIS_URL")
        self.rate_limiter = (
            rate_limiter
            if rate_limiter is not None
            else RateLimiter(redis_url=resolved_redis_url or "redis://localhost:6379")
        )
        if rate_limiter is None and resolved_redis_url is None:
            self.rate_limiter._redis = None
        from .key_rotation import KeyRotator

        self._key_rotator: KeyRotator = KeyRotator(self)

    def load(self) -> None:
        with self._config_lock:
            config = self._load_config()
            config_changed = self._key_rotator.ensure_key_ids(config)
            config_changed = self._key_rotator.cleanup_expired_rotations(config) or config_changed
            if config_changed and self.api_keys_path is not None:
                self._key_rotator.write_config(config)
            self.security_policy = load_security_policy(self.security_config_path)
            self._loaded_keys = config.keys
            self.keys_by_value = {}
            self._keys_by_id = {}
            self._hashed_keys = []
            self._key_rotator.cancel_rotation_cleanup_timers()
            for item in config.keys:
                if item.key_id is not None:
                    self._keys_by_id[item.key_id] = item
                if item.key is not None:
                    self.keys_by_value[item.key] = item.model_copy(
                        update={"matched_slot": "current"}
                    )
                if item.key_hash is not None:
                    self._hashed_keys.append(item)
                    runtime_key = self._runtime_plaintext_by_hash.get(item.key_hash)
                    if runtime_key is not None:
                        self.keys_by_value[runtime_key] = item.model_copy(
                            update={"key": runtime_key, "matched_slot": "current"}
                        )
                if self._key_rotator.is_previous_key_active(item):
                    self._key_rotator.schedule_rotation_cleanup(item)
            self._rate_windows = defaultdict(
                list,
                {key: self._rate_windows.get(key, []) for key in self.keys_by_value},
            )
        from src.serving.api import auth as auth_package

        auth_package.logger.info(
            "api_keys_loaded",
            path=str(self.api_keys_path) if self.api_keys_path else "env_only",
            keys=self.configured_key_count,
        )

    def reload(self, *_: object) -> None:
        self.load()
        from src.serving.api import auth as auth_package

        auth_package.logger.info(
            "api_keys_reloaded",
            path=str(self.api_keys_path) if self.api_keys_path else "env_only",
        )

    def register_signal_handlers(self) -> None:
        sighup = getattr(signal, "SIGHUP", None)
        if sighup is None:
            return
        try:
            signal.signal(sighup, self.reload)
        except ValueError:
            from src.serving.api import auth as auth_package

            auth_package.logger.warning("api_keys_signal_handler_skipped", reason="not_main_thread")

    def ensure_usage_table(self) -> None:
        from .middleware import ensure_usage_table

        ensure_usage_table(self)

    def authenticate(self, api_key: str) -> TenantKey | None:
        for item in self.keys_by_value.values():
            runtime_key = item.key
            if runtime_key is None:
                continue
            if secrets.compare_digest(runtime_key, api_key):
                return item.model_copy(update={"key": api_key, "matched_slot": "current"})
        for item in self._hashed_keys:
            if item.key_hash is None:
                continue
            if verify_api_key(api_key, item.key_hash):
                return item.model_copy(update={"key": api_key, "matched_slot": "current"})
        for item in self._loaded_keys:
            if not self._key_rotator.is_previous_key_active(item) or item.previous_key_hash is None:
                continue
            if verify_api_key(api_key, item.previous_key_hash):
                return item.model_copy(update={"key": api_key, "matched_slot": "previous"})
        return None

    @property
    def configured_key_count(self) -> int:
        return len(self._loaded_keys) if self._loaded_keys else len(self.keys_by_value)

    def has_configured_keys(self) -> bool:
        return bool(self.keys_by_value or self._hashed_keys)

    def is_rate_limited(self, tenant_key: TenantKey) -> bool:
        now = self.time_source()
        cutoff = now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        key_id = self._rate_limit_key(tenant_key)
        window = [stamp for stamp in self._rate_windows[key_id] if stamp > cutoff]
        self._rate_windows[key_id] = window
        if len(window) >= tenant_key.rate_limit_rpm:
            return True
        window.append(now)
        return False

    async def check_rate_limit(self, tenant_key: TenantKey) -> tuple[bool, int, int]:
        is_allowed, remaining, reset_at = await self.rate_limiter.check(
            self._rate_limit_key(tenant_key),
            tenant_key.rate_limit_rpm,
        )
        if (
            is_allowed
            and remaining == tenant_key.rate_limit_rpm
            and getattr(self.rate_limiter, "_redis", None) is not None
        ):
            now = self.time_source()
            cutoff = now - DEFAULT_RATE_LIMIT_WINDOW_SECONDS
            key = self._rate_limit_key(tenant_key)
            window = [stamp for stamp in self._rate_windows[key] if stamp > cutoff]
            self._rate_windows[key] = window
            if len(window) >= tenant_key.rate_limit_rpm:
                if window:
                    reset_at = int(window[0] + DEFAULT_RATE_LIMIT_WINDOW_SECONDS)
                return False, 0, reset_at
            window.append(now)
            reset_at = int(window[0] + DEFAULT_RATE_LIMIT_WINDOW_SECONDS)
            return True, max(0, tenant_key.rate_limit_rpm - len(window)), reset_at
        return is_allowed, remaining, reset_at

    def is_failed_auth_limited(self, client_ip: str) -> bool:
        now = self.time_source()
        cutoff = now - FAILED_AUTH_WINDOW_SECONDS
        window = [stamp for stamp in self._failed_auth_windows[client_ip] if stamp > cutoff]
        self._failed_auth_windows[client_ip] = window
        return len(window) > self.security_policy.max_failed_auth_per_ip_per_hour

    def record_failed_auth(self, client_ip: str) -> bool:
        now = self.time_source()
        cutoff = now - FAILED_AUTH_WINDOW_SECONDS
        window = [stamp for stamp in self._failed_auth_windows[client_ip] if stamp > cutoff]
        window.append(now)
        self._failed_auth_windows[client_ip] = window
        return len(window) > self.security_policy.max_failed_auth_per_ip_per_hour

    def clear_failed_auth(self, client_ip: str) -> None:
        self._failed_auth_windows.pop(client_ip, None)

    def is_entity_allowed(self, tenant_key: TenantKey, entity_type: str) -> bool:
        if tenant_key.allowed_entity_types is None:
            return True
        return entity_type in tenant_key.allowed_entity_types

    def record_usage(self, tenant_key: TenantKey, endpoint: str) -> None:
        from .middleware import record_usage

        record_usage(self, tenant_key, endpoint)

    def list_keys_with_usage(self) -> list[dict]:
        return self._key_rotator.list_keys_with_usage()

    def usage_by_tenant(self) -> list[dict]:
        from .middleware import usage_by_tenant

        return usage_by_tenant(self)

    def create_key(self, payload: KeyCreateRequest) -> TenantKey:
        return self._key_rotator.create_key(payload)

    def revoke_key(self, api_key: str) -> bool:
        return self._key_rotator.revoke_key(api_key)

    def rotate_key(self, key_id: str) -> tuple[TenantKey, datetime]:
        return self._key_rotator.rotate_key(key_id)

    def revoke_old_key(self, key_id: str) -> bool:
        return self._key_rotator.revoke_old_key(key_id)

    def get_rotation_status(self, key_id: str) -> dict[str, object]:
        return self._key_rotator.get_rotation_status(key_id)

    def shutdown(self) -> None:
        self._key_rotator.shutdown()

    def _load_config(self) -> ApiKeysConfig:
        if self.api_keys_path and self.api_keys_path.exists():
            raw = self.api_keys_path.read_text(encoding="utf-8")
            if yaml is not None:
                data = yaml.safe_load(raw) or {}
            else:  # pragma: no cover
                data = json.loads(raw)
            return ApiKeysConfig.model_validate(data)
        return ApiKeysConfig(keys=self._legacy_env_keys())

    def _legacy_env_keys(self) -> list[TenantKey]:
        raw = os.getenv("AGENTFLOW_API_KEYS", "")
        if not raw.strip():
            return []
        items = []
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" in pair:
                key, name = pair.split(":", 1)
            else:
                key, name = pair, "unnamed"
            items.append(
                TenantKey(
                    key_id=self._key_rotator.generate_key_id("default", name.strip(), set()),
                    key=key.strip(),
                    name=name.strip(),
                    tenant="default",
                    rate_limit_rpm=DEFAULT_RATE_LIMIT_RPM,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                )
            )
        return items

    def _rate_limit_key(self, tenant_key: TenantKey) -> str:
        return tenant_key.key or tenant_key.key_hash or tenant_key.name

    def _matches_key_material(self, item: TenantKey, value: str) -> bool:
        if item.key is not None and secrets.compare_digest(item.key, value):
            return True
        if item.key_hash is not None and secrets.compare_digest(item.key_hash, value):
            return True
        cached_key = item.key_hash and self._runtime_plaintext_by_hash.get(item.key_hash)
        if cached_key is not None and secrets.compare_digest(cached_key, value):
            return True
        if item.previous_key_hash is not None and verify_api_key(value, item.previous_key_hash):
            return True
        if item.key_hash is None:
            return False
        return verify_api_key(value, item.key_hash)


def get_auth_manager(request: Request) -> AuthManager:
    return cast(AuthManager, request.app.state.auth_manager)
