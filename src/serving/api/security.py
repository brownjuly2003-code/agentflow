from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

import bcrypt
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer",
}

SecurityHeadersMiddleware = Callable[
    [Request, Callable[[Request], Awaitable[Response]]],
    Awaitable[Response],
]

DEFAULT_SECURITY_CONFIG_PATH = Path(
    os.getenv("AGENTFLOW_SECURITY_CONFIG_FILE", "config/security.yaml")
)


class RequestBodyTooLargeError(Exception):
    pass


class SecurityPolicy(BaseModel):
    # M-C4 (2026-06-05): argon2id replaced bcrypt as the default scheme for
    # NEW key material so `authenticate()` can pair every hash with a
    # deterministic peppered lookup digest (see `compute_key_lookup`) and
    # resolve the candidate in O(1). Legacy bcrypt hashes keep verifying.
    key_hashing: str = "argon2id"
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


# OWASP password-storage cheat-sheet minimum for argon2id (m=19 MiB, t=2,
# p=1). API keys are high-entropy (256-bit token_urlsafe material), so the
# slow hash is defence-in-depth for a leaked config, not the primary barrier;
# the moderate profile keeps the single indexed verify per cold auth cheap.
_ARGON2_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)

# Deterministic lookup digests are domain-separated by an HMAC pepper so a
# leaked api_keys.yaml cannot be joined against digests of the same key
# material computed elsewhere. Production may override the pepper via env;
# changing it invalidates stored `key_lookup` values (keys then fall back to
# the O(n) verify scan until re-issued — see docs/runbooks/auth-401-spike.md).
DEFAULT_KEY_LOOKUP_PEPPER = "agentflow-key-lookup-v1"


def compute_key_lookup(value: str, pepper: str | None = None) -> str:
    resolved = (
        pepper
        if pepper is not None
        else os.getenv("AGENTFLOW_KEY_LOOKUP_PEPPER", DEFAULT_KEY_LOOKUP_PEPPER)
    )
    return hmac.new(resolved.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_api_key(value: str, rounds: int, scheme: str = "argon2id") -> str:
    if scheme == "argon2id":
        return _ARGON2_HASHER.hash(value)
    if scheme == "bcrypt":
        return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")
    raise ValueError(f"Unsupported key-hashing scheme: {scheme!r}")


def verify_api_key(value: str, key_hash: str) -> bool:
    if key_hash.startswith("$argon2"):
        try:
            return _ARGON2_HASHER.verify(key_hash, value)
        except (
            argon2_exceptions.VerifyMismatchError,
            argon2_exceptions.VerificationError,
            argon2_exceptions.InvalidHashError,
        ):
            return False
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


def build_security_headers_middleware(
    config_path: Path | str | None = None,
) -> SecurityHeadersMiddleware:
    policy = load_security_policy(config_path)

    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        response: Response
        if content_length is not None and int(content_length) > policy.request_size_limit_bytes:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
        else:
            if content_length is None:
                received_bytes = 0
                chunks: list[bytes] = []
                try:
                    async for chunk in request.stream():
                        received_bytes += len(chunk)
                        if received_bytes > policy.request_size_limit_bytes:
                            raise RequestBodyTooLargeError
                        chunks.append(chunk)
                except RequestBodyTooLargeError:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large."},
                    )
                else:
                    body = b"".join(chunks)
                    request._body = body
                    response = await call_next(request)
            else:
                response = await call_next(request)
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers.setdefault(header_name, header_value)
        return response

    return security_headers
