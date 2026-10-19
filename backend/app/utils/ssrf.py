"""SSRF protection utilities with pre-resolution, IP validation, and DNS-pinned outbound transport.

Implements strict defense against Server-Side Request Forgery (SSRF), DNS rebinding,
and TOCTOU attacks when fetching external scholarship and university pages.
"""

import ipaddress
import socket
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit

import httpcore
from httpcore._backends.sync import SyncBackend
import httpx


# ============================================================================
# Exceptions
# ============================================================================

class SSRFSecurityError(Exception):
    """Base exception for all SSRF security violations."""
    pass


class SSRFInvalidURLError(SSRFSecurityError):
    """Raised when URL syntax is invalid or uses a disallowed scheme/credentials."""
    pass


class SSRFBlockedIPError(SSRFSecurityError):
    """Raised when destination resolves to private, loopback, or reserved IP."""
    pass


class SSRFDNSResolutionError(SSRFSecurityError):
    """Raised when hostname resolution fails or returns no valid addresses."""
    pass


class SSRFMaxRedirectsError(SSRFSecurityError):
    """Raised when the maximum allowable redirect limit is exceeded."""
    pass


class SSRFResponseTooLargeError(SSRFSecurityError):
    """Raised when response body or Content-Length exceeds maximum allowable limit."""
    pass


# Default maximum response size (5 MiB = 5,242,880 bytes)
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


# ============================================================================
# Blocked CIDR Networks (IPv4 and IPv6)
# ============================================================================

BLOCKED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network (RFC 1122)
    ipaddress.ip_network("10.0.0.0/8"),         # Private network (RFC 1918)
    ipaddress.ip_network("100.64.0.0/10"),      # Shared address space (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback (RFC 1122)
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / Cloud metadata (RFC 3927)
    ipaddress.ip_network("172.16.0.0/12"),      # Private network (RFC 1918)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments (RFC 6890)
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("192.88.99.0/24"),     # 6to4 Relay Anycast (RFC 7526)
    ipaddress.ip_network("192.168.0.0/16"),     # Private network (RFC 1918)
    ipaddress.ip_network("198.18.0.0/15"),      # Network benchmark tests (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast (RFC 5771)
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use (RFC 1112)
    ipaddress.ip_network("255.255.255.255/32"), # Limited Broadcast (RFC 919)
]

BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network("::/128"),             # Unspecified (RFC 4291)
    ipaddress.ip_network("::1/128"),            # Loopback (RFC 4291)
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation (RFC 6052)
    ipaddress.ip_network("100::/64"),           # Discard-only (RFC 6666)
    ipaddress.ip_network("2001:db8::/32"),      # Documentation (RFC 3849)
    ipaddress.ip_network("2002::/16"),          # 6to4 (RFC 3056)
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (RFC 4193)
    ipaddress.ip_network("fe80::/10"),          # Link-Local Unicast (RFC 4291)
    ipaddress.ip_network("ff00::/8"),           # Multicast (RFC 4291)
]

ALLOWED_SCHEMES = {"http", "https"}


# ============================================================================
# IP and URL Validation
# ============================================================================

def is_safe_ip(ip_str: str) -> Tuple[bool, str]:
    """Inspect an IP string against blocked address spaces.

    Handles standard IPv4, standard IPv6, and IPv4-mapped IPv6 addresses.
    Returns (True, '') if safe, or (False, reason) if blocked.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, f"Invalid IP address format: {ip_str}"

    # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    # Check built-in properties
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False, f"IP address {ip} is non-public (private/loopback/link-local/multicast/reserved)"

    # Check against explicit IPv4 networks
    if isinstance(ip, ipaddress.IPv4Address):
        for net in BLOCKED_IPV4_NETWORKS:
            if ip in net:
                return False, f"IPv4 address {ip} falls inside blocked network {net}"

    # Check against explicit IPv6 networks
    elif isinstance(ip, ipaddress.IPv6Address):
        for net in BLOCKED_IPV6_NETWORKS:
            if ip in net:
                return False, f"IPv6 address {ip} falls inside blocked network {net}"

    return True, ""


def validate_url_syntax(url_str: str) -> Tuple[str, str, int]:
    """Validate URL syntax, scheme, credentials, and extract (scheme, hostname, port).

    Raises SSRFInvalidURLError on any invalid syntax.
    """
    if not url_str or not isinstance(url_str, str):
        raise SSRFInvalidURLError("URL must be a non-empty string")

    clean_url = url_str.strip()
    try:
        parts = urlsplit(clean_url)
    except Exception as exc:
        raise SSRFInvalidURLError(f"Malformed URL: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFInvalidURLError(
            f"Unsupported scheme '{scheme}'. Only HTTP and HTTPS are permitted."
        )

    if parts.username or parts.password:
        raise SSRFInvalidURLError(
            "URLs containing embedded userinfo/credentials (user:pass@host) are prohibited."
        )

    hostname = parts.hostname
    if not hostname:
        raise SSRFInvalidURLError("URL must contain a valid hostname.")

    # Determine port
    port = parts.port
    if port is None:
        port = 443 if scheme == "https" else 80
    elif not (1 <= port <= 65535):
        raise SSRFInvalidURLError(f"Invalid port: {port}")

    return scheme, hostname, port


def resolve_and_validate_hostname(hostname: str) -> List[str]:
    """Resolve hostname to IP addresses and ensure ALL resolved IPs are safe.

    Fails closed: if ANY returned IP is in a private/blocked space, raises
    SSRFBlockedIPError.
    """
    # Check if hostname is already a literal IP
    try:
        ipaddress.ip_address(hostname)
        is_safe, reason = is_safe_ip(hostname)
        if not is_safe:
            raise SSRFBlockedIPError(reason)
        return [hostname]
    except ValueError:
        pass  # Hostname is a domain name, proceed to DNS resolution

    try:
        addrinfo = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except Exception as exc:
        raise SSRFDNSResolutionError(
            f"DNS resolution failed for hostname '{hostname}': {exc}"
        ) from exc

    if not addrinfo:
        raise SSRFDNSResolutionError(
            f"DNS resolution returned no records for hostname '{hostname}'"
        )

    resolved_ips: Set[str] = set()
    for item in addrinfo:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        resolved_ips.add(ip_str)

    if not resolved_ips:
        raise SSRFDNSResolutionError(
            f"No IP addresses could be extracted for hostname '{hostname}'"
        )

    # Strictly validate every resolved IP address
    for ip_str in resolved_ips:
        is_safe, reason = is_safe_ip(ip_str)
        if not is_safe:
            raise SSRFBlockedIPError(
                f"Hostname '{hostname}' resolved to unsafe destination: {reason}"
            )

    return sorted(list(resolved_ips))


# ============================================================================
# DNS-Pinned Outbound Transport
# ============================================================================

class PinnedSyncBackend(SyncBackend):
    """Custom network backend that connects TCP sockets directly to a validated IP.

    When start_tls is subsequently called, the original server_hostname is preserved,
    ensuring TLS SNI and server certificate validation remain authentic while the
    underlying connection cannot be redirected via DNS rebinding.
    """

    def __init__(self, pinned_ip: str) -> None:
        super().__init__()
        self.pinned_ip = pinned_ip

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Any] = None,
    ) -> Any:
        # Override the destination host with the pre-validated pinned IP
        return super().connect_tcp(
            host=self.pinned_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class SSRFSafeTransport(httpx.BaseTransport):
    """HTTP transport that resolves and pins network destinations per-request."""

    def __init__(
        self,
        pinned_ip: str,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        super().__init__()
        self.pinned_ip = pinned_ip
        self.max_response_bytes = max_response_bytes
        backend = PinnedSyncBackend(pinned_ip)
        self._pool = httpcore.ConnectionPool(network_backend=backend)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,  # Propagates timeout configuration to httpcore
        )
        resp = self._pool.handle_request(req)

        # Enforce maximum response-body size limit
        try:
            # 1. Early Content-Length check if header is present
            content_length = None
            for name, val in resp.headers:
                if name.lower() == b"content-length":
                    try:
                        content_length = int(val.decode("ascii").strip())
                    except (ValueError, UnicodeDecodeError):
                        pass
                    break

            if content_length is not None and content_length > self.max_response_bytes:
                raise SSRFResponseTooLargeError(
                    f"Response Content-Length ({content_length} bytes) exceeds "
                    f"maximum allowable limit of {self.max_response_bytes} bytes."
                )

            # 2. Cumulative stream read check (guards against missing/misleading Content-Length)
            total_bytes = 0
            chunks = []
            for chunk in resp.stream:
                total_bytes += len(chunk)
                if total_bytes > self.max_response_bytes:
                    raise SSRFResponseTooLargeError(
                        f"Response body exceeded maximum limit of {self.max_response_bytes} "
                        f"bytes while downloading stream."
                    )
                chunks.append(chunk)

            body = b"".join(chunks)
        except Exception:
            resp.close()
            raise

        return httpx.Response(
            status_code=resp.status,
            headers=resp.headers,
            stream=httpx.ByteStream(body),
            request=request,
            extensions=resp.extensions,
        )

    def close(self) -> None:
        self._pool.close()


# ============================================================================
# Safe Fetch Function with Manual Redirect Revalidation
# ============================================================================

def safe_fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    max_redirects: int = 3,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> httpx.Response:
    """Fetch an HTTP/HTTPS URL securely.

    1. Validates URL syntax and ensures no userinfo credentials exist.
    2. Resolves DNS and validates that ALL returned IPs are public/safe.
    3. Pins the connection to the validated IP to prevent DNS rebinding.
    4. Enforces TLS certificate validation against the original hostname.
    5. Disables automatic redirects; inspects and re-validates each redirect hop.
    6. Limits redirect depth to a maximum of 3.
    7. Enforces maximum allowable response-body size (default: 5 MiB).
    """
    current_url = url
    redirect_count = 0
    request_headers = headers.copy() if headers else {}
    request_headers.setdefault("User-Agent", "ScholarSwarm-Agent/1.0 (+https://scholarswarm.internal)")

    while True:
        # Validate URL and scheme
        scheme, hostname, port = validate_url_syntax(current_url)

        # Resolve DNS and validate IP destinations
        safe_ips = resolve_and_validate_hostname(hostname)
        pinned_ip = safe_ips[0]

        transport = SSRFSafeTransport(
            pinned_ip=pinned_ip,
            max_response_bytes=max_response_bytes,
        )
        try:
            with httpx.Client(
                transport=transport,
                timeout=timeout,
                follow_redirects=False,  # CRITICAL: Manual redirect inspection
            ) as client:
                response = client.request(
                    method=method,
                    url=current_url,
                    headers=request_headers,
                )
        finally:
            transport.close()

        # Check for HTTP redirect response (301, 302, 303, 307, 308)
        if response.status_code in (301, 302, 303, 307, 308):
            redirect_count += 1
            if redirect_count > max_redirects:
                raise SSRFMaxRedirectsError(
                    f"Redirect limit exceeded ({max_redirects} maximum)."
                )

            location = response.headers.get("Location")
            if not location:
                # 3xx without Location header, return as-is
                return response

            # Resolve relative redirect targets against the current URL
            next_url = urljoin(current_url, location)
            current_url = next_url
            continue

        return response
