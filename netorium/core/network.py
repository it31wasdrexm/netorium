"""Cross-platform LAN address helpers for controller enrollment."""

from __future__ import annotations

import socket


def detect_lan_ipv4() -> str | None:
    """Return the preferred non-loopback IPv4 address for this host, if any."""
    for resolver in (_lan_ipv4_via_udp_route, _lan_ipv4_via_hostname):
        address = resolver()
        if address is not None:
            return address
    return None


def format_url_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def build_enrollment_urls(*, host: str, port: int) -> tuple[str, str | None]:
    """Return local and optional LAN enrollment URLs for controller clients."""
    local = f"http://{format_url_host('127.0.0.1')}:{port}/enroll"
    if host not in {"0.0.0.0", "::", "127.0.0.1", "localhost"}:
        return f"http://{format_url_host(host)}:{port}/enroll", None

    lan_host = detect_lan_ipv4()
    if lan_host is None or lan_host == "127.0.0.1":
        return local, None
    return local, f"http://{format_url_host(lan_host)}:{port}/enroll"


def _lan_ipv4_via_udp_route() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return address if _is_usable_lan_ipv4(address) else None


def _lan_ipv4_via_hostname() -> str | None:
    try:
        results = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None

    for result in results:
        address = str(result[4][0])
        if _is_usable_lan_ipv4(address):
            return address
    return None


def _is_usable_lan_ipv4(address: str) -> bool:
    return not address.startswith("127.") and address != "0.0.0.0"
