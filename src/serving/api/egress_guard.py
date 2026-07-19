"""Egress URL guard against SSRF.

Webhook and alert targets are tenant-controlled URLs that the server fetches.
Without a guard a tenant can point them at loopback / private / link-local /
cloud-metadata addresses and use the delivery result (status / error) as an
SSRF oracle to map and reach the internal network (audit_28_06_26.md #2).

This module resolves the host and rejects any URL that is not an http(s) target
resolving exclusively to public unicast addresses. It is applied both at
registration time (reject early, 4xx) and immediately before each delivery
(narrowing the DNS-rebinding window — a name that resolved public at creation
could later point at an internal IP).

``AGENTFLOW_EGRESS_ALLOWED_HOSTS`` is an opt-in escape hatch (default empty, so
production keeps the full guard): a comma-separated allowlist of exact
hostnames a controlled deployment trusts even though they resolve to a
private/loopback address — e.g. the ``host.docker.internal`` gateway the e2e
compose stack delivers to, or the ``127.0.0.1`` relay the staging kind cluster
stands up. It never relaxes the guard for tenant traffic, only for hosts the
operator explicitly listed.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWLIST_ENV = "AGENTFLOW_EGRESS_ALLOWED_HOSTS"


def _allowed_hosts() -> frozenset[str]:
    """Return the operator-configured opt-in allowlist (exact hostnames,
    lower-cased). Read per call so deployments can set it via the environment
    without an import-time freeze; empty by default."""
    raw = os.getenv(_ALLOWLIST_ENV, "")
    return frozenset(host.strip().lower() for host in raw.split(",") if host.strip())


class UnsafeEgressURLError(ValueError):
    """Raised when an outbound URL is not a public http(s) target."""


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    # An IPv4-mapped IPv6 address (``::ffff:169.254.169.254``) embeds an IPv4
    # target the connect will actually reach. CPython's ``is_private`` /
    # ``is_link_local`` do reflect the embedded v4 on 3.11 for the ranges that
    # matter here, but that is version-dependent (tightened in 3.13); unwrap to
    # the embedded IPv4 and judge THAT, so the guard does not hinge on the stdlib
    # version of the prod image. Same for 6to4 (``2002::/16``) which carries a v4
    # in the next 32 bits. (pre-pen-test audit, S-1 feeder)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _ip_is_public(str(addr.ipv4_mapped))
        if addr.sixtofour is not None:
            return _ip_is_public(str(addr.sixtofour))
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_public_url(url: str) -> None:
    """Raise :class:`UnsafeEgressURLError` unless ``url`` is an http(s) URL whose
    host resolves *only* to public unicast addresses.

    Resolution is synchronous (``socket.getaddrinfo``); call it via
    ``asyncio.to_thread`` on the event loop. IP-literal hosts resolve to
    themselves, so loopback/private/link-local literals are rejected without any
    network DNS.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeEgressURLError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise UnsafeEgressURLError("missing host")
    if host.lower() in _allowed_hosts():
        # Operator explicitly trusts this host (controlled test/relay target).
        # The scheme check above still applies; only the public-address check
        # is waived.
        return
    port = parts.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeEgressURLError(f"host does not resolve: {host}") from exc
    resolved = {str(info[4][0]) for info in infos}
    if not resolved:
        raise UnsafeEgressURLError(f"host does not resolve: {host}")
    for ip in resolved:
        if not _ip_is_public(ip):
            raise UnsafeEgressURLError(f"host {host} resolves to non-public address {ip}")
