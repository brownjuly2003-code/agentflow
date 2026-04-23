from __future__ import annotations

import secrets

import duckdb
import structlog

from src.serving.api.security import verify_api_key

from .key_rotation import KeyRotator, rotate_all_keys
from .manager import (
    DEFAULT_API_KEYS_FILE,
    DEFAULT_RATE_LIMIT_RPM,
    DEFAULT_USAGE_DB_PATH,
    ApiKeysConfig,
    AuthManager,
    KeyCreateRequest,
    TenantKey,
    get_auth_manager,
    get_current_tenant_id,
)
from .middleware import AuthMiddleware, build_auth_middleware, require_admin_key, require_auth

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_API_KEYS_FILE",
    "DEFAULT_RATE_LIMIT_RPM",
    "DEFAULT_USAGE_DB_PATH",
    "ApiKeysConfig",
    "AuthManager",
    "AuthMiddleware",
    "KeyCreateRequest",
    "KeyRotator",
    "TenantKey",
    "build_auth_middleware",
    "duckdb",
    "get_auth_manager",
    "get_current_tenant_id",
    "logger",
    "require_admin_key",
    "require_auth",
    "rotate_all_keys",
    "secrets",
    "verify_api_key",
]
