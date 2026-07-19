"""SSRF egress-guard tests (no Docker, no network).

IP-literal hosts resolve to themselves via getaddrinfo, so the loopback/private/
link-local cases need no network; hostname cases mock getaddrinfo. Covers
audit_28_06_26.md #2 — webhook/alert targets must reject internal addresses.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from src.serving.api.egress_guard import (
    UnsafeEgressURLError,
    _PinnedIPTransport,
    pinned_transport,
    resolve_public_ip,
    validate_public_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",  # loopback
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5:6379/",  # private
        "http://192.168.1.1/",  # private
        "http://172.16.0.1/",  # private
        "http://[::1]/",  # IPv6 loopback
        "http://0.0.0.0/",  # unspecified
        "https://[fd00::1]/",  # IPv6 unique-local
        "http://[fe80::1]/",  # IPv6 link-local
        # IPv4-mapped IPv6 embedding an internal v4 target — the connect reaches
        # the embedded IPv4, so the guard must judge that, not the wrapper
        # (pre-pen-test audit, S-1 feeder; robust across CPython versions).
        "http://[::ffff:169.254.169.254]/latest/meta-data/",  # mapped metadata
        "http://[::ffff:127.0.0.1]/",  # mapped loopback
        "http://[::ffff:10.0.0.1]/",  # mapped private
        "http://[2002:a9fe:a9fe::1]/",  # 6to4 embedding 169.254.169.254
    ],
)
def test_validate_rejects_non_public_addresses(url: str) -> None:
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url(url)


def test_mapped_public_ipv4_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The unwrap must not over-reject: a mapped *public* IPv4 stays public.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:93.184.216.34", 80, 0, 0))
        ],
    )
    validate_public_url("http://mapped-public.example.com/hook")  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://",  # missing host
        "not-a-url",  # no scheme
    ],
)
def test_validate_rejects_bad_scheme_or_host(url: str) -> None:
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url(url)


def test_validate_allows_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )
    validate_public_url("http://example.com/hook")  # must not raise


def test_validate_rejects_public_name_resolving_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DNS-rebinding shape: an innocuous host that resolves to an internal IP.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))],
    )
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url("http://internal.example.com/")


def test_validate_rejects_when_any_resolved_ip_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A host resolving to both a public and a private IP must be rejected.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ],
    )
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url("http://dual.example.com/")


# --- Opt-in egress allowlist (AGENTFLOW_EGRESS_ALLOWED_HOSTS) -----------------
# A controlled deployment (e2e compose, staging kind relay) must be able to
# deliver to the specific callback host it stands up — which deliberately
# resolves to a private/loopback address — without weakening the guard for
# tenant traffic. The allowlist is opt-in (default empty) and matches exact
# hostnames, case-insensitively, while still enforcing the http(s) scheme.


def test_allowlisted_loopback_host_is_permitted(monkeypatch: pytest.MonkeyPatch) -> None:
    # Staging shape: the in-pod relay listens on 127.0.0.1 (normally rejected as
    # loopback); the operator allowlists it so the webhook callback is delivered.
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    validate_public_url("http://127.0.0.1:18080/callback")  # must not raise


def test_allowlisted_gateway_host_skips_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    # E2E shape: host.docker.internal resolves to a private gateway IP. An
    # allowlisted host is trusted without any DNS resolution at all.
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "host.docker.internal")

    def _no_resolution(*_a: object, **_k: object) -> list[object]:
        raise AssertionError("allowlisted host must not be resolved")

    monkeypatch.setattr(socket, "getaddrinfo", _no_resolution)
    validate_public_url("http://host.docker.internal:9000/callback")  # must not raise


def test_allowlist_matches_host_case_insensitively(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "Host.Docker.Internal")
    validate_public_url("http://host.docker.internal/cb")  # must not raise


def test_allowlist_parses_comma_list_and_ignores_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", " , 127.0.0.1 ,host.docker.internal, ")
    validate_public_url("http://127.0.0.1:18080/callback")  # must not raise
    validate_public_url("http://host.docker.internal/cb")  # must not raise


def test_allowlist_still_enforces_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url("file://127.0.0.1/etc/passwd")


def test_allowlist_only_exempts_listed_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    # A different private host, not on the list, is still rejected.
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "127.0.0.1")
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url("http://10.0.0.5:6379/")


def test_empty_allowlist_preserves_loopback_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default/empty env must not weaken the guard.
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "")
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url("http://127.0.0.1/x")


# --- IP pinning: DNS-rebinding TOCTOU close (audit S-1) -----------------------
# resolve_public_ip resolves+validates once and returns the approved public IP;
# pinned_transport connects to that literal so httpx never re-resolves the
# hostname between the check and the connect. The Host header and TLS SNI stay
# on the hostname.


def test_resolve_public_ip_returns_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )
    assert resolve_public_ip("http://example.com/hook") == "93.184.216.34"


def test_resolve_public_ip_rejects_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))],
    )
    with pytest.raises(UnsafeEgressURLError):
        resolve_public_ip("http://internal.example.com/")


def test_resolve_public_ip_allowlisted_is_not_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    # Allowlisted hosts are trusted by name and connected as-is: resolve returns
    # None (no resolution) and the factory yields the default transport.
    monkeypatch.setenv("AGENTFLOW_EGRESS_ALLOWED_HOSTS", "host.docker.internal")

    def _no_resolution(*_a: object, **_k: object) -> list[object]:
        raise AssertionError("allowlisted host must not be resolved")

    monkeypatch.setattr(socket, "getaddrinfo", _no_resolution)
    assert resolve_public_ip("http://host.docker.internal:9000/cb") is None
    assert pinned_transport("http://host.docker.internal:9000/cb", None) is None


def test_pinned_transport_connects_to_validated_ip_not_rebound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Rebinding shape: the first resolution (the guard) returns a public IP; a
    # later one would flip to cloud-metadata. Pinning must connect to the
    # validated public IP and never re-resolve, so the rebind never takes effect.
    calls = {"n": 0}

    def _flipping(host: str, *_a: object, **_k: object) -> list[object]:
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", _flipping)

    pinned_ip = resolve_public_ip("http://rebind.example.com/hook")
    assert pinned_ip == "93.184.216.34"
    assert calls["n"] == 1  # resolved exactly once, by the guard

    transport = pinned_transport("http://rebind.example.com/hook", pinned_ip)
    assert isinstance(transport, _PinnedIPTransport)

    captured: dict[str, object] = {}

    async def _fake_super(self: object, request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        captured["host_header"] = request.headers.get("host")
        captured["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super)

    request = httpx.Request("POST", "http://rebind.example.com/hook", content=b"x")
    response = asyncio.run(transport.handle_async_request(request))

    assert response.status_code == 200
    # The socket target is the validated public IP literal — no second lookup.
    assert captured["host"] == "93.184.216.34"
    # Host header + TLS identity still key on the hostname.
    assert captured["host_header"] == "rebind.example.com"
    assert captured["sni"] == "rebind.example.com"
    # getaddrinfo was consulted exactly once (the guard); the transport never
    # re-resolved, so the rebound metadata address was never reachable.
    assert calls["n"] == 1
