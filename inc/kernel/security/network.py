"""Small, business-agnostic network boundary helpers."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable


def resolve_client_ip(
    *,
    peer: str | None,
    forwarded_for: str | None,
    trusted_proxy_cidrs: Iterable[str],
) -> str:
    """Resolve the originating address without trusting spoofed headers.

    ``X-Forwarded-For`` is considered only when the direct peer belongs to a
    configured proxy network.  The chain is walked from right to left so a
    proxy that appends the actual peer address cannot be bypassed by a client
    supplied left-most value.
    """

    peer_address = _parse_address(peer)
    if peer_address is None:
        return "unknown"
    trusted_networks = _parse_networks(trusted_proxy_cidrs)
    if not any(peer_address in network for network in trusted_networks):
        return str(peer_address)

    candidates = [
        address
        for address in (_parse_address(value) for value in (forwarded_for or "").split(","))
        if address is not None
    ]
    chain = [*candidates, peer_address]
    for address in reversed(chain):
        if not any(address in network for network in trusted_networks):
            return str(address)
    return str(candidates[0]) if candidates else str(peer_address)


def _parse_address(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _parse_networks(
    values: Iterable[str],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError:
            continue
    return tuple(networks)


__all__ = ["resolve_client_ip"]
