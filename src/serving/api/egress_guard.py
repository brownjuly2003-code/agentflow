"""Egress URL guard against SSRF.

Webhook and alert targets are tenant-controlled URLs that the server fetches.
Without a guard a tenant can point them at loopback / private / link-local /
cloud-metadata addresses and use the delivery result (status / error) as an
SSRF oracle to map and reach the internal network (audit_28_06_26.md #2).

This module resolves the host and rejects any URL that is not an http(s) target
resolving exclusively to public unicast addresses. It is applied both at
registration time (reject early, 4xx) and immediately before each delivery.

**DNS-rebinding TOCTOU (audit S-1).** A validate-then-``post`` pair is racy: the
guard resolves the host and approves it, then ``httpx`` re-resolves the *same
hostname* to open the socket, so a low-TTL name that flips public→internal
between the two lookups slips past the guard and is fetched. Re-validating
before each delivery only narrows the window. The fix here removes the second
lookup entirely: :func:`resolve_public_ip` resolves and validates the host
**once** and returns the approved public IP, and :func:`pinned_transport` pins
the connection to *that IP literal* — the transport never resolves the hostname
again. The original ``Host`` header and TLS SNI / certificate hostname are
preserved (via the ``sni_hostname`` request extension) so routing and TLS
verification still key on the hostname, not the IP.

``AGENTFLOW_EGRESS_ALLOWED_HOSTS`` is an opt-in escape hatch (default empty, so
production keeps the full guard): a comma-separated allowlist of exact
hostnames a controlled deployment trusts even though they resolve to a
private/loopback address — e.g. the ``host.docker.internal`` gateway the e2e
compose stack delivers to, or the ``127.0.0.1`` relay the staging kind cluster
stands up. It never relaxes the guard for tenant traffic, only for hosts the
operator explicitly listed. Allowlisted hosts are *not* pinned (they are trusted
by name); every other host is.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

import httpx

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


def _split_egress_url(url: str) -> tuple[str, str, int, bool]:
    """Parse ``url`` and enforce the scheme/host rules shared by both entry
    points. Return ``(scheme, host, port, allowlisted)``; raise
    :class:`UnsafeEgressURLError` on a non-http(s) scheme or a missing host.
    ``allowlisted`` is ``True`` when the operator opted this exact host out of
    the public-address check."""
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
        return scheme, host, parts.port or (443 if scheme == "https" else 80), True
    port = parts.port or (443 if scheme == "https" else 80)
    return scheme, host, port, False


def _resolve_public_ips(host: str, port: int) -> set[str]:
    """Resolve ``host`` and return the set of resolved addresses, having verified
    that **every** one is a public unicast address. Raise
    :class:`UnsafeEgressURLError` if the host does not resolve or any resolved
    address is non-public (so a host answering with both a public and an internal
    IP is rejected, not partially trusted).

    Resolution is synchronous (``socket.getaddrinfo``); call it off the event
    loop via ``asyncio.to_thread``. IP-literal hosts resolve to themselves, so
    loopback/private/link-local literals are rejected without any network DNS.
    """
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
    return resolved


def validate_public_url(url: str) -> None:
    """Raise :class:`UnsafeEgressURLError` unless ``url`` is an http(s) URL whose
    host resolves *only* to public unicast addresses.

    Registration-time gate (reject obviously-unsafe targets early with a 4xx).
    Delivery-time code should call :func:`resolve_public_ip` instead, which
    additionally pins the connection and closes the rebinding TOCTOU.
    """
    _scheme, host, port, allowlisted = _split_egress_url(url)
    if allowlisted:
        return
    _resolve_public_ips(host, port)


def resolve_public_ip(url: str) -> str | None:
    """Resolve ``url``'s host to a single validated public IP and return it, so
    the caller can pin the connection to that literal (closing the DNS-rebinding
    TOCTOU — no second name resolution happens between this check and the
    connect).

    Return ``None`` for an operator-allowlisted host: those are trusted by name
    and connected as-is, without pinning. Raise :class:`UnsafeEgressURLError` on
    a bad scheme / missing host / unresolvable host / any non-public resolved
    address — exactly the rejections :func:`validate_public_url` makes.

    Synchronous DNS; call via ``asyncio.to_thread`` on the event loop.
    """
    _scheme, host, port, allowlisted = _split_egress_url(url)
    if allowlisted:
        return None
    ips = _resolve_public_ips(host, port)
    # Deterministic pick; every address in the set was verified public above, so
    # any of them is a safe pin target.
    return sorted(ips)[0]


class _PinnedIPTransport(httpx.AsyncHTTPTransport):
    """httpx transport that rewrites each request's host to a pre-validated
    public IP literal before connecting, so httpx performs **no** second DNS
    resolution (the rebinding TOCTOU close). The original ``Host`` header — set
    by httpx at request-build time from the hostname URL — is left untouched, and
    the hostname is carried into the TLS handshake as ``sni_hostname`` so SNI and
    certificate verification still key on the hostname rather than the IP."""

    def __init__(self, hostname: str, pinned_ip: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._hostname = hostname
        self._pinned_ip = pinned_ip

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.extensions = {**request.extensions, "sni_hostname": self._hostname}
        request.url = request.url.copy_with(host=self._pinned_ip)
        return await super().handle_async_request(request)


def pinned_transport(url: str, pinned_ip: str | None) -> httpx.AsyncBaseTransport | None:
    """Build the transport for delivering to ``url``.

    Given the ``pinned_ip`` from :func:`resolve_public_ip`, return a transport
    that connects to that IP literal while preserving the hostname's ``Host``
    header and TLS identity. Return ``None`` when ``pinned_ip`` is ``None`` (an
    allowlisted host) so the caller uses httpx's default transport unchanged.
    """
    if pinned_ip is None:
        return None
    host = urlsplit(url).hostname or ""
    return _PinnedIPTransport(host, pinned_ip)
