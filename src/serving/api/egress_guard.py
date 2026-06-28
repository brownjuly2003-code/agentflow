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
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeEgressURLError(ValueError):
    """Raised when an outbound URL is not a public http(s) target."""


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
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
