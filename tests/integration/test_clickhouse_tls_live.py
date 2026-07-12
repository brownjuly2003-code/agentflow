"""Live TLS proof for the ClickHouse client (audit P2-3).

`secure=true` has a unit-level pin (`tests/unit/test_clickhouse_tls_context.py`)
but a TLS posture is only real against a real handshake, so this suite drives
an actual HTTPS ClickHouse fronted by a *private* CA and asserts all three
sides of the contract:

- the private CA bundle (`ca_cert`) is sufficient — queries work;
- the private CA bundle is necessary — the system trust store refuses the
  same endpoint (a client silently falling back to "trust anything" would
  also pass the first test, so this one is the load-bearing one);
- hostname verification is on — the same CA, the same server, but addressed
  by an identity outside the certificate's SANs, is refused.

Needs a server whose certificate chains to CLICKHOUSE_TLS_LIVE_CA and lists
`localhost` as its only SAN (the bring-up recipe lives in
`_NEXT_SESSION.md` / docs/helm-deployment.md). CI's plain ClickHouse service
does not speak TLS, so the suite skips there — this is a stand probe, like
the Mac perf recipes.
"""

from __future__ import annotations

import os

import pytest

from src.serving.backends.clickhouse_backend import BackendExecutionError, ClickHouseBackend

LIVE_HOST = os.getenv("CLICKHOUSE_TLS_LIVE_HOST")
LIVE_PORT = int(os.getenv("CLICKHOUSE_TLS_LIVE_PORT", "18443"))
LIVE_USER = os.getenv("CLICKHOUSE_TLS_LIVE_USER", "agentflow")
LIVE_PASSWORD = os.getenv("CLICKHOUSE_TLS_LIVE_PASSWORD", "agentflow")
LIVE_DATABASE = os.getenv("CLICKHOUSE_TLS_LIVE_DATABASE", "default")
LIVE_CA = os.getenv("CLICKHOUSE_TLS_LIVE_CA")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (LIVE_HOST and LIVE_CA),
        reason="CLICKHOUSE_TLS_LIVE_HOST/CLICKHOUSE_TLS_LIVE_CA not configured "
        "(live TLS ClickHouse required)",
    ),
]


def _backend(*, host: str | None = None, ca_cert: str | None = None) -> ClickHouseBackend:
    return ClickHouseBackend(
        host=host or LIVE_HOST or "localhost",
        port=LIVE_PORT,
        user=LIVE_USER,
        password=LIVE_PASSWORD,
        database=LIVE_DATABASE,
        secure=True,
        timeout_seconds=10,
        ca_cert=ca_cert,
    )


def test_private_ca_bundle_is_sufficient() -> None:
    rows = _backend(ca_cert=LIVE_CA).execute("SELECT 41 + 1 AS answer")

    assert rows
    assert rows[0]["answer"] == 42


def test_system_trust_store_refuses_the_private_ca() -> None:
    # The load-bearing negative: a client that "worked" in the test above by
    # trusting anything would pass it just as well — this proves verification
    # actually runs and actually fails without the operator-supplied bundle.
    with pytest.raises(BackendExecutionError, match="(?i)certif"):
        _backend(ca_cert=None).execute("SELECT 1")


def test_hostname_verification_is_on() -> None:
    # Same CA, same server — addressed as 127.0.0.1, which the certificate's
    # SANs (DNS:localhost) do not cover. A client that skipped hostname
    # checks would happily answer.
    with pytest.raises(BackendExecutionError, match="(?i)hostname|certif"):
        _backend(host="127.0.0.1", ca_cert=LIVE_CA).execute("SELECT 1")
