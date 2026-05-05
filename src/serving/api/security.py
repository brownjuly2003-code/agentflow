from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import bcrypt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer",
}

DEFAULT_SECURITY_CONFIG_PATH = Path(
    os.getenv("AGENTFLOW_SECURITY_CONFIG_FILE", "config/security.yaml")
)


class SecurityPolicy(BaseModel):
    key_hashing: str = "bcrypt"
    bcrypt_rounds: int = Field(default=12, ge=4)
    min_key_length: int = Field(default=32, ge=1)
    max_failed_auth_per_ip_per_hour: int = Field(default=10, ge=1)
    sensitive_headers_to_redact: list[str] = Field(
        default_factory=lambda: ["Authorization", "X-API-Key"]
    )
    request_size_limit_bytes: int = Field(default=1_048_576, ge=1)


def load_security_policy(config_path: Path | str | None = None) -> SecurityPolicy:
    path = Path(config_path) if config_path is not None else DEFAULT_SECURITY_CONFIG_PATH
    if yaml is None or not path.exists():
        return SecurityPolicy()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SecurityPolicy.model_validate(raw.get("security") or {})


def hash_api_key(value: str, rounds: int) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_api_key(value: str, key_hash: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode("utf-8"), key_hash.encode("utf-8"))
    except ValueError:
        return False


def redact_sensitive_headers(
    headers: Mapping[str, str],
    sensitive_headers: list[str] | None = None,
) -> dict[str, str]:
    if sensitive_headers is None:
        sensitive_headers = SecurityPolicy().sensitive_headers_to_redact
    sensitive = {header.lower() for header in sensitive_headers}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        redacted[key] = "[REDACTED]" if key.lower() in sensitive else value
    return redacted


def build_security_headers_middleware(config_path: Path | str | None = None):
    policy = load_security_policy(config_path)

    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > policy.request_size_limit_bytes:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
        else:
            response = await call_next(request)
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers.setdefault(header_name, header_value)
        return response

    return security_headers
