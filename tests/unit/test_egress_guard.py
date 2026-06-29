"""SSRF egress-guard tests (no Docker, no network).

IP-literal hosts resolve to themselves via getaddrinfo, so the loopback/private/
link-local cases need no network; hostname cases mock getaddrinfo. Covers
audit_28_06_26.md #2 — webhook/alert targets must reject internal addresses.
"""

from __future__ import annotations

import socket

import pytest

from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url


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
    ],
)
def test_validate_rejects_non_public_addresses(url: str) -> None:
    with pytest.raises(UnsafeEgressURLError):
        validate_public_url(url)


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
