"""Who the failed-auth throttle blocks, and who it must never block (audit FB-06).

Three defects are pinned here, each of which shipped and each of which turns the
throttle from a brute-force brake into something worse:

* the middleware answered **429 before the key was looked at**, so eleven junk
  requests from one address took every caller sharing that address offline for an
  hour. Behind a gateway with no ``AGENTFLOW_TRUSTED_PROXIES`` every caller shares
  one address -- and ``values-production.yaml`` sanctions exactly that shape
  (``ingress.enabled=false``), so this was a full-tenant outage for the price of
  eleven requests;
* the admin surface counted its failures in the **same** window as ``/v1``, so a
  scan against tenant routes locked the operator out of ``/v1/admin`` -- the
  surface they need while the scan is happening;
* ``X-Forwarded-For`` was read from the **left**, which is the one element the
  client writes itself. With trusted proxies configured as documented, an
  attacker rotating the header got a fresh window on every request and the
  throttle counted to one, forever.

The throttle's job is to blunt scanning and log-flooding, not to be a
denial-of-service primitive: API keys are 256-bit random values, so brute force
was never the thing it was holding back (``AuthManager.is_failed_auth_limited``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from agentflow_runtime.constants import FAILED_AUTH_SCOPE_ADMIN, FAILED_AUTH_SCOPE_API
from agentflow_runtime.serving.api.auth import AuthManager, build_auth_middleware
from agentflow_runtime.serving.api.auth.middleware import _client_ip, require_admin_key
from agentflow_runtime.serving.api.security import compute_key_lookup, hash_api_key

ADMIN_KEY = "admin-secret"
TENANT_KEY = "tenant-order-key"
LEGACY_KEY = "legacy-bcrypt-key"
FAILED_AUTH_LIMIT = 2
BCRYPT_TEST_ROUNDS = 4

# The peer address every TestClient request arrives from.
PEER = "testclient"


def _entry(plaintext: str, *, name: str, indexed: bool, scheme: str) -> dict:
    entry = {
        "key_id": f"key-{name}",
        "key_hash": hash_api_key(plaintext, rounds=BCRYPT_TEST_ROUNDS, scheme=scheme),
        "name": name,
        "tenant": "acme",
        "rate_limit_rpm": 120,
        "created_at": "2026-06-05",
    }
    if indexed:
        entry["key_lookup"] = compute_key_lookup(plaintext)
    return entry


def _write_config(tmp_path: Path) -> tuple[Path, Path]:
    keys_path = tmp_path / "config" / "api_keys.yaml"
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text(
        yaml.safe_dump(
            {
                "keys": [
                    # Issued since M-C4: argon2id hash + peppered lookup digest.
                    _entry(TENANT_KEY, name="indexed", indexed=True, scheme="argon2id"),
                    # Pre-M-C4 shape: bcrypt, resolvable only by the O(n) scan.
                    _entry(LEGACY_KEY, name="legacy", indexed=False, scheme="bcrypt"),
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    security_path = tmp_path / "config" / "security.yaml"
    security_path.write_text(
        yaml.safe_dump(
            {
                "security": {
                    "key_hashing": "argon2id",
                    "bcrypt_rounds": BCRYPT_TEST_ROUNDS,
                    "min_key_length": 8,
                    "max_failed_auth_per_ip_per_hour": FAILED_AUTH_LIMIT,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return keys_path, security_path


@pytest.fixture(autouse=True)
def _no_trusted_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """No proxy is trusted unless the test says so."""
    monkeypatch.delenv("AGENTFLOW_TRUSTED_PROXIES", raising=False)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    keys_path, security_path = _write_config(tmp_path)
    application = FastAPI()
    application.state.auth_manager = AuthManager(
        api_keys_path=keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key=ADMIN_KEY,
        security_config_path=security_path,
    )
    application.state.auth_manager.load()
    application.state.auth_manager.ensure_usage_table()
    application.middleware("http")(build_auth_middleware())

    @application.get("/v1/metrics/revenue")
    async def revenue() -> dict[str, int]:
        return {"revenue": 1}

    # AuthMiddleware hands /v1/admin* straight to the route, so the admin
    # dependency is the only thing standing in front of this one.
    admin = APIRouter(dependencies=[Depends(require_admin_key)])

    @admin.get("/v1/admin/ping")
    async def admin_ping() -> dict[str, bool]:
        return {"ok": True}

    application.include_router(admin)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _trip_tenant_window(client: TestClient) -> None:
    for _ in range(FAILED_AUTH_LIMIT + 1):
        client.get("/v1/metrics/revenue", headers={"X-API-Key": "wrong"})


def _trip_admin_window(client: TestClient) -> None:
    for _ in range(FAILED_AUTH_LIMIT + 1):
        client.get("/v1/admin/ping", headers={"X-Admin-Key": "wrong"})


# --- who the request is attributed to ---------------------------------------


def _request(peer: str, forwarded_for: str | None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/metrics/revenue",
            "raw_path": b"/v1/metrics/revenue",
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "server": ("api", 80),
            "client": (peer, 51234),
            "headers": headers,
        }
    )


def test_forwarded_for_is_ignored_when_the_peer_is_not_a_trusted_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", "10.0.0.1")
    assert _client_ip(_request("203.0.113.9", "198.51.100.1")) == "203.0.113.9"


def test_forwarded_for_is_read_from_the_right_not_the_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client owns the leftmost element; the proxy owns the rightmost one.

    A caller that sends its own ``X-Forwarded-For`` has that value carried at the
    left of the chain forever -- the proxies only append. Reading it made the
    window key attacker-chosen.
    """
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", "10.0.0.1")
    request = _request("10.0.0.1", "i-made-this-up, 198.51.100.7")

    assert _client_ip(request) == "198.51.100.7"


def test_forwarded_for_skips_the_trusted_hops_it_recognises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two proxies in front: the last one names the first one, and only the hop
    beyond the trust boundary is the client."""
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")
    request = _request("10.0.0.2", "203.0.113.4, 10.0.0.1")

    assert _client_ip(request) == "203.0.113.4"


def test_an_all_trusted_chain_keys_on_the_outermost_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing in the chain crossed a boundary this deployment can name, so the
    key is a trusted address rather than client-supplied text."""
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", "10.0.0.1, 10.0.0.2")

    assert _client_ip(_request("10.0.0.2", "10.0.0.1, 10.0.0.1")) == "10.0.0.1"


def test_an_empty_forwarded_for_falls_back_to_the_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", "10.0.0.1")

    assert _client_ip(_request("10.0.0.1", " , ")) == "10.0.0.1"


def test_a_rotated_forwarded_for_cannot_rotate_the_window(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bypass, end to end: a fresh spoofed leftmost element on every request
    used to mean a fresh window on every request."""
    monkeypatch.setenv("AGENTFLOW_TRUSTED_PROXIES", PEER)

    statuses = [
        client.get(
            "/v1/metrics/revenue",
            headers={"X-API-Key": "wrong", "X-Forwarded-For": f"10.9.9.{index}, 198.51.100.7"},
        ).status_code
        for index in range(FAILED_AUTH_LIMIT + 1)
    ]

    assert statuses == [401] * FAILED_AUTH_LIMIT + [429]


# --- what a tripped window may and may not do -------------------------------


def test_a_valid_key_still_serves_from_a_throttled_address(client: TestClient) -> None:
    """The shared-address lockout. Behind a gateway every tenant arrives from one
    address, so a throttle that rejects before reading the key is an outage
    anyone can trigger for the price of three requests."""
    _trip_tenant_window(client)
    assert client.get("/v1/metrics/revenue", headers={"X-API-Key": "wrong"}).status_code == 429

    response = client.get("/v1/metrics/revenue", headers={"X-API-Key": TENANT_KEY})

    assert response.status_code == 200


def test_a_tenant_scan_does_not_throttle_the_admin_surface(client: TestClient) -> None:
    _trip_tenant_window(client)

    response = client.get("/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 200


def test_admin_guesses_do_not_throttle_tenant_traffic(client: TestClient) -> None:
    _trip_admin_window(client)

    # A valid key serves whatever the window says, so it cannot show that the
    # window was left alone. A *wrong* one can: on an untouched tenant window the
    # first miss is a plain 401, where a shared window would already be at 429.
    wrong = client.get("/v1/metrics/revenue", headers={"X-API-Key": "wrong"})
    valid = client.get("/v1/metrics/revenue", headers={"X-API-Key": TENANT_KEY})

    assert wrong.status_code == 401
    assert valid.status_code == 200


def test_the_admin_surface_still_throttles_its_own_guesses(client: TestClient) -> None:
    statuses = [
        client.get("/v1/admin/ping", headers={"X-Admin-Key": "wrong"}).status_code
        for _ in range(FAILED_AUTH_LIMIT + 1)
    ]

    assert statuses == [401] * FAILED_AUTH_LIMIT + [429]


def test_the_real_admin_key_still_works_from_a_throttled_address(client: TestClient) -> None:
    _trip_admin_window(client)

    response = client.get("/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 200


def test_a_successful_admin_call_clears_only_the_admin_window(
    client: TestClient,
    app: FastAPI,
) -> None:
    manager = app.state.auth_manager
    _trip_tenant_window(client)
    _trip_admin_window(client)

    assert client.get("/v1/admin/ping", headers={"X-Admin-Key": ADMIN_KEY}).status_code == 200

    assert not manager.is_failed_auth_limited(PEER, FAILED_AUTH_SCOPE_ADMIN)
    assert manager.is_failed_auth_limited(PEER)


def test_a_non_ascii_admin_key_is_refused_rather_than_fatal(client: TestClient) -> None:
    """Header values reach the app latin-1 decoded. ``secrets.compare_digest``
    raises TypeError on a non-ASCII ``str``, which turned a wrong key into a 500
    -- an unauthenticated caller choosing the response code."""
    response = client.get(
        "/v1/admin/ping",
        headers=[(b"x-admin-key", ADMIN_KEY.encode("ascii") + bytes([0xFC]))],
    )

    assert response.status_code == 401


# --- cost of being throttled -------------------------------------------------


def test_the_window_stops_growing_once_it_has_tripped(app: FastAPI) -> None:
    """Every failed attempt is recorded now, including the ones answered with
    429, so the window has to stop accumulating or a scanner buys one float per
    request for an hour."""
    manager = app.state.auth_manager

    for _ in range(200):
        manager.record_failed_auth("203.0.113.5")

    window = manager._failed_auth_windows[FAILED_AUTH_SCOPE_API, "203.0.113.5"]
    assert len(window) == FAILED_AUTH_LIMIT + 1
    assert manager.is_failed_auth_limited("203.0.113.5")


def test_a_legacy_bcrypt_key_is_not_resolvable_while_throttled(client: TestClient) -> None:
    """The deliberate edge of the fix, stated rather than discovered.

    Resolving a pre-M-C4 entry costs one bcrypt verify **per configured key**,
    which is the amplification the early gate used to prevent. Under throttle the
    lookup is capped to the constant-work paths, so a legacy key holder sharing a
    throttled address is refused until the key is rotated onto an argon2id entry
    with a lookup digest. A key issued since M-C4 is unaffected.
    """
    _trip_tenant_window(client)

    # Order matters: a success clears the window, so the legacy key is asked
    # first, while the address is still throttled.
    legacy = client.get("/v1/metrics/revenue", headers={"X-API-Key": LEGACY_KEY})
    indexed = client.get("/v1/metrics/revenue", headers={"X-API-Key": TENANT_KEY})

    assert legacy.status_code == 429
    assert indexed.status_code == 200
