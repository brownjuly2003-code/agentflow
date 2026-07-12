"""Production-profile transport gate (audit P2-3).

The backends have long *supported* TLS (``CLICKHOUSE_SECURE``, ``rediss://``,
``sslmode=`` in the control-plane DSN) but nothing required it, so a scale
deployment could silently speak plaintext to external stores. This module is
the requirement: on ``AGENTFLOW_PROFILE=production`` the boot refuses
insecure transport to any external ClickHouse/Redis/PostgreSQL.

Two deliberate exemptions:

- loopback / unix-socket targets — the bytes never leave the host;
- ``AGENTFLOW_INSECURE_TRANSPORT_OK="clickhouse,redis,postgres"`` — an
  explicit, greppable operator decision (e.g. in-cluster plaintext behind a
  NetworkPolicy), taken per store rather than as a global off switch.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

PROFILE_ENV = "AGENTFLOW_PROFILE"
INSECURE_OK_ENV = "AGENTFLOW_INSECURE_TRANSPORT_OK"
_PROFILES = {"demo", "dev", "production"}
_TLS_SSLMODES = {"require", "verify-ca", "verify-full"}


class InsecureTransportError(RuntimeError):
    """The production profile refused a plaintext hop to an external store."""


def resolve_profile(env: Mapping[str, str] | None = None) -> str:
    """Resolve the deployment profile: explicit env wins, demo mode implies
    demo, everything else is dev."""
    env = os.environ if env is None else env
    raw = (env.get(PROFILE_ENV) or "").strip().lower()
    if raw:
        if raw not in _PROFILES:
            raise ValueError(
                f"{PROFILE_ENV}={raw!r} is not a profile; expected one of {sorted(_PROFILES)}."
            )
        return raw
    if (env.get("AGENTFLOW_DEMO_MODE") or "").strip().lower() == "true":
        return "demo"
    return "dev"


def _is_loopback(host: str | None) -> bool:
    host = (host or "").strip().lower()
    return host in {"", "localhost", "::1", "[::1]"} or host.startswith("127.")


def _pg_dsn_transport_ok(dsn: str) -> bool:
    if "://" in dsn:
        parts = urlsplit(dsn)
        host = parts.hostname
        sslmode = (parse_qs(parts.query).get("sslmode") or [""])[0]
    else:
        # Keyword form: "host=... dbname=... sslmode=...". Quoted values are
        # out of scope here — the gate only needs host and sslmode, which are
        # never quoted in practice.
        fields = dict(pair.split("=", 1) for pair in dsn.split() if "=" in pair)
        host = fields.get("host", "")
        sslmode = fields.get("sslmode", "")
    if _is_loopback(host):
        return True
    return sslmode in _TLS_SSLMODES


def assert_secure_transport(
    *,
    profile: str,
    serving_config: Mapping,
    redis_url: str = "",
    pg_dsn: str = "",
    env: Mapping[str, str] | None = None,
) -> None:
    """Refuse to boot a production profile over plaintext external transport.

    ``serving_config`` is the dict from ``load_serving_backend_config``;
    ``redis_url``/``pg_dsn`` are passed only when the deployment actually
    uses those stores (empty string = not in play).
    """
    if profile != "production":
        return
    env = os.environ if env is None else env
    overrides = {
        token.strip().lower()
        for token in (env.get(INSECURE_OK_ENV) or "").split(",")
        if token.strip()
    }

    problems: list[str] = []

    if serving_config.get("backend") == "clickhouse" and "clickhouse" not in overrides:
        clickhouse = serving_config.get("clickhouse") or {}
        if not clickhouse.get("secure") and not _is_loopback(str(clickhouse.get("host", ""))):
            problems.append(
                "clickhouse: external serving store over plaintext HTTP "
                "(set CLICKHOUSE_SECURE=true / serving.clickhouse.secure)"
            )

    if redis_url and "redis" not in overrides:
        parts = urlsplit(redis_url)
        if parts.scheme in {"redis", ""} and not _is_loopback(parts.hostname):
            problems.append(
                "redis: external cache/rate-limit hop over plaintext "
                "(use rediss:// or a local socket)"
            )

    if pg_dsn and "postgres" not in overrides and not _pg_dsn_transport_ok(pg_dsn):
        problems.append("postgres: control-plane DSN without sslmode=require/verify-ca/verify-full")

    if problems:
        raise InsecureTransportError(
            "production profile refuses insecure transport:\n- "
            + "\n- ".join(problems)
            + f"\nA deliberate plaintext hop (e.g. in-cluster behind a NetworkPolicy) "
            f'must be named in {INSECURE_OK_ENV}, e.g. "clickhouse,redis".'
        )


def resolve_cors_origins(env: Mapping[str, str] | None = None) -> list[str]:
    """Parse AGENTFLOW_CORS_ORIGINS; a wildcard is demo-only.

    The middleware runs with ``allow_credentials=True``, and Starlette
    responds to ``allow_origins=["*"]`` by echoing the caller's Origin —
    which turns "any website may read authenticated responses" into
    configuration. Demo mode accepts that; every other profile refuses.
    """
    env = os.environ if env is None else env
    origins = [
        origin.strip()
        for origin in (env.get("AGENTFLOW_CORS_ORIGINS") or "http://localhost:3000").split(",")
        if origin.strip()
    ]
    if "*" in origins and resolve_profile(env) != "demo":
        raise InsecureTransportError(
            "AGENTFLOW_CORS_ORIGINS contains '*' while CORS runs with credentials; "
            "that is demo-only. List the allowed origins explicitly."
        )
    return origins
