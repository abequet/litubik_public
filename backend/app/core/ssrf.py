# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSRF guards for outbound URLs whose host comes from user input.

The hosted instance can reach cloud metadata endpoints (169.254.169.254), its
own API (localhost:8000) and any service on the private network. Several
endpoints navigate/fetch a URL the user supplied (EZProxy entry points, custom
proxy entry points, redirect targets) — this module rejects any URL that resolves
to a private/loopback/link-local/reserved address before we ever connect.

TOCTOU note: `validate_public_url` resolves the host itself, so a name that
resolves only to public addresses at check time could in theory re-resolve to a
private one at connect time (DNS rebinding). Blocking the obvious literal-IP and
first-resolution cases already closes the practical attack surface these
findings describe; a rebinding-proof fix would require pinning the resolved IP
into the connection, which the vendored HTTP stacks don't expose cleanly.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = ("http", "https")

# Internal ranges that `ipaddress` does not count as private: the carrier-grade
# NAT space, which hosting platforms use for their own internal network (the
# Dockerfile trusts it as the proxy's), and deprecated IPv6 site-local.
_ALSO_INTERNAL = (ipaddress.ip_network("100.64.0.0/10"),
                  ipaddress.ip_network("fec0::/10"))


class SSRFError(ValueError):
    """A user-supplied URL points at a forbidden (private/internal) target."""


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> refuse
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified
            or any(addr in net for net in _ALSO_INTERNAL
                   if net.version == addr.version))


def _resolved_ips(host: str, port: int | None) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port or None,
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFError(f"Hôte introuvable : {host}") from e
    return [info[4][0] for info in infos]


def validate_public_url(url: str, *, allow_schemes=ALLOWED_SCHEMES) -> str:
    """Return `url` unchanged, or raise SSRFError if its scheme is not allowed
    or its host resolves to a private/internal address."""
    parsed = urlparse((url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in allow_schemes:
        raise SSRFError(f"Schéma d'URL non autorisé : {scheme or '(vide)'}")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL sans hôte")
    # literal IP: check directly (no DNS)
    try:
        ipaddress.ip_address(host)
        if _ip_is_blocked(host):
            raise SSRFError(f"Adresse IP interne interdite : {host}")
        return url
    except ValueError:
        pass
    for ip in _resolved_ips(host, parsed.port):
        if _ip_is_blocked(ip):
            raise SSRFError(
                f"L'hôte {host} pointe vers une adresse interne ({ip})")
    return url


_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}


def validate_url_shape(url: str, *, allow_schemes=ALLOWED_SCHEMES) -> str:
    """Config-time check: reject a bad scheme, a literal private/loopback IP, or
    an obvious localhost name — WITHOUT resolving DNS. A not-yet-resolvable but
    legitimate host (e.g. an institution's EZProxy set up offline) still saves;
    the connect-time guard (`validate_public_url`) resolves it for real when we
    actually navigate to it. Catches the documented literal-IP exploits
    (169.254.169.254, localhost:8000) at the boundary."""
    parsed = urlparse((url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in allow_schemes:
        raise SSRFError(f"Schéma d'URL non autorisé : {scheme or '(vide)'}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SSRFError("URL sans hôte")
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        raise SSRFError(f"Hôte local interdit : {host}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return url  # a hostname — defer to the connect-time resolver
    if _ip_is_blocked(host):
        raise SSRFError(f"Adresse IP interne interdite : {host}")
    return url


def is_public_url(url: str, *, allow_schemes=ALLOWED_SCHEMES) -> bool:
    try:
        validate_public_url(url, allow_schemes=allow_schemes)
        return True
    except SSRFError:
        return False


def block_private_redirects(response) -> None:
    """httpx 'response' event hook: abort a redirect whose Location resolves to
    a private/internal address. Use with `follow_redirects=True`:

        httpx.Client(follow_redirects=True,
                     event_hooks={"response": [block_private_redirects]})
    """
    if response.is_redirect:
        location = response.headers.get("location")
        if location:
            validate_public_url(urljoin(str(response.url), location))
