"""Deterministic unit and security tests for SSRF protection utilities.

Mocks DNS resolution and network transports to verify that loopback, private,
link-local, cloud metadata, multicast, and redirect bypasses are strictly blocked.
No live external network requests are made.
"""

import socket
from unittest.mock import MagicMock, patch
import pytest

from backend.app.utils.ssrf import (
    DEFAULT_MAX_RESPONSE_BYTES,
    PinnedSyncBackend,
    SSRFBlockedIPError,
    SSRFDNSResolutionError,
    SSRFInvalidURLError,
    SSRFMaxRedirectsError,
    SSRFResponseTooLargeError,
    SSRFSafeTransport,
    is_safe_ip,
    resolve_and_validate_hostname,
    safe_fetch_url,
    validate_url_syntax,
)


# ============================================================================
# IP Classification Unit Tests
# ============================================================================

@pytest.mark.parametrize(
    "ip,expected_safe",
    [
        # Loopback
        ("127.0.0.1", False),
        ("127.0.0.2", False),
        ("127.255.255.255", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("::", False),
        # Private RFC 1918
        ("10.0.0.1", False),
        ("10.254.0.1", False),
        ("172.16.0.1", False),
        ("172.31.255.255", False),
        ("192.168.1.1", False),
        ("192.168.100.254", False),
        # Link-local and Cloud Metadata
        ("169.254.169.254", False),
        ("169.254.1.1", False),
        ("fe80::1", False),
        # Multicast & Reserved
        ("224.0.0.1", False),
        ("239.255.255.255", False),
        ("240.0.0.1", False),
        ("255.255.255.255", False),
        ("ff02::1", False),
        # IPv6 Unique Local
        ("fc00::1", False),
        ("fd00::1", False),
        # IPv4-mapped IPv6
        ("::ffff:127.0.0.1", False),
        ("::ffff:10.0.0.1", False),
        ("::ffff:169.254.169.254", False),
        # Public Safe IPs
        ("93.184.215.14", True),     # example.com IPv4
        ("8.8.8.8", True),            # Public DNS IPv4
        ("2606:2800:220:1:248:1893:25c8:1946", True),  # example.com IPv6
    ],
)
def test_is_safe_ip(ip: str, expected_safe: bool):
    """Verify IP classification against blocked networks."""
    safe, reason = is_safe_ip(ip)
    assert safe == expected_safe, f"Expected safe={expected_safe} for {ip}, got {safe}. Reason: {reason}"


# ============================================================================
# URL Syntax & Scheme Tests
# ============================================================================

def test_validate_url_syntax_valid():
    """Verify standard HTTP/HTTPS URLs parse correctly."""
    scheme, host, port = validate_url_syntax("https://ethz.ch/en/studies.html")
    assert scheme == "https"
    assert host == "ethz.ch"
    assert port == 443

    scheme, host, port = validate_url_syntax("http://example.edu:8080/path")
    assert scheme == "http"
    assert host == "example.edu"
    assert port == 8080


@pytest.mark.parametrize(
    "disallowed_url",
    [
        "file:///etc/passwd",
        "ftp://ftp.example.edu/file.pdf",
        "gopher://gopher.example.edu",
        "ldap://localhost",
        "http://admin:secret@example.com/login",  # Embedded credentials
        "https://user@example.com/test",          # Embedded username
        "http:///no-host",
        "",
        "not-a-url",
    ],
)
def test_validate_url_syntax_disallowed(disallowed_url: str):
    """Verify disallowed schemes, credentials, and malformed URLs are rejected."""
    with pytest.raises(SSRFInvalidURLError):
        validate_url_syntax(disallowed_url)


# ============================================================================
# DNS Resolution & Validation Tests (Mocked)
# ============================================================================

def test_resolve_hostname_literal_private_ip():
    """Verify literal private IP in URL is rejected immediately."""
    with pytest.raises(SSRFBlockedIPError):
        resolve_and_validate_hostname("127.0.0.1")

    with pytest.raises(SSRFBlockedIPError):
        resolve_and_validate_hostname("169.254.169.254")


def test_resolve_hostname_localhost():
    """Verify localhost resolving to 127.0.0.1 is rejected."""
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))
        ]
        with pytest.raises(SSRFBlockedIPError):
            resolve_and_validate_hostname("localhost")


def test_resolve_hostname_mixed_dns_fails_closed():
    """Verify DNS returning both public and private IP fails closed (DNS rebinding defense)."""
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
        ]
        with pytest.raises(SSRFBlockedIPError) as exc_info:
            resolve_and_validate_hostname("malicious-rebind.internal")
        err_msg = str(exc_info.value)
        assert "unsafe destination" in err_msg and "10.0.0.1" in err_msg


def test_resolve_hostname_dns_error():
    """Verify socket error raises SSRFDNSResolutionError."""
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
        with pytest.raises(SSRFDNSResolutionError):
            resolve_and_validate_hostname("nonexistent.invalid")


# ============================================================================
# Fetch and Redirect Handling Tests (Mocked)
# ============================================================================

def test_safe_fetch_blocks_private_url():
    """Verify safe_fetch_url blocks direct calls to loopback/private URLs."""
    with pytest.raises(SSRFBlockedIPError):
        safe_fetch_url("http://127.0.0.1:8000/api/admin")

    with pytest.raises(SSRFBlockedIPError):
        safe_fetch_url("http://169.254.169.254/latest/meta-data/")


def test_safe_fetch_valid_public_mocked():
    """Verify successful deterministic fetch when DNS resolves to safe public IP."""
    import httpcore
    import httpx

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        # Mock the underlying ConnectionPool to avoid live network access
        mock_response = httpcore.Response(
            status=200,
            headers=[(b"content-type", b"text/html; charset=utf-8")],
            content=b"<html><body>Scholarship Details</body></html>",
        )
        with patch.object(httpcore.ConnectionPool, "handle_request", return_value=mock_response):
            resp = safe_fetch_url("https://www.example.edu/scholarships")
            assert resp.status_code == 200
            assert "Scholarship Details" in resp.text


def test_safe_fetch_blocks_redirect_to_private_ip():
    """Verify HTTP redirect targeting private IP / cloud metadata is blocked."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        # First call for benign.edu resolves to public IP
        # Second call for metadata or internal host
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        # First request returns 302 to metadata service
        redirect_response = httpcore.Response(
            status=302,
            headers=[(b"location", b"http://169.254.169.254/latest/meta-data/")],
            content=b"",
        )
        with patch.object(httpcore.ConnectionPool, "handle_request", return_value=redirect_response):
            with pytest.raises(SSRFBlockedIPError):
                safe_fetch_url("https://www.benign.edu/redirect-me")


def test_safe_fetch_enforces_max_redirects():
    """Verify exceeding maximum redirect count raises SSRFMaxRedirectsError."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        # Perpetual redirect loop between public URLs
        redirect_response = httpcore.Response(
            status=302,
            headers=[(b"location", b"https://www.benign.edu/loop")],
            content=b"",
        )
        with patch.object(httpcore.ConnectionPool, "handle_request", return_value=redirect_response):
            with pytest.raises(SSRFMaxRedirectsError) as exc_info:
                safe_fetch_url("https://www.benign.edu/loop", max_redirects=3)
            assert "Redirect limit exceeded" in str(exc_info.value)


# ============================================================================
# Direct DNS-Pinning, Timeout, and Response Size Tests
# ============================================================================

def test_pinned_sync_backend_connects_to_pinned_ip_not_hostname():
    """Verify PinnedSyncBackend passes the validated pinned IP to connect_tcp, not the hostname."""
    from httpcore._backends.sync import SyncBackend

    backend = PinnedSyncBackend(pinned_ip="93.184.215.14")
    with patch.object(SyncBackend, "connect_tcp") as mock_connect:
        mock_connect.return_value = MagicMock()

        # Caller requests connection with domain hostname
        backend.connect_tcp(
            host="ethz.ch",
            port=443,
            timeout=5.0,
            local_address=None,
            socket_options=None,
        )

        mock_connect.assert_called_once()
        kwargs = mock_connect.call_args.kwargs
        # Assert destination host was strictly swapped to the pinned IP
        assert kwargs["host"] == "93.184.215.14"
        assert kwargs["host"] != "ethz.ch"
        assert kwargs["port"] == 443
        assert kwargs["timeout"] == 5.0


def test_safe_fetch_timeout_propagation():
    """Verify timeout settings in safe_fetch_url propagate into httpcore.Request extensions."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        captured_requests = []
        def fake_handle_request(req):
            captured_requests.append(req)
            return httpcore.Response(
                status=200,
                headers=[(b"content-type", b"text/html")],
                content=b"OK",
            )

        with patch.object(httpcore.ConnectionPool, "handle_request", side_effect=fake_handle_request):
            safe_fetch_url("https://www.example.edu/path", timeout=7.5)

            assert len(captured_requests) == 1
            extensions = captured_requests[0].extensions
            assert "timeout" in extensions
            assert extensions["timeout"]["connect"] == 7.5
            assert extensions["timeout"]["read"] == 7.5


def test_safe_fetch_rejects_oversized_content_length():
    """Verify response with Content-Length exceeding limit is rejected early and closed."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        mock_resp = httpcore.Response(
            status=200,
            headers=[(b"content-length", b"10485760")],  # 10 MiB header
            content=b"never-reached",
        )
        with patch.object(mock_resp, "close", wraps=mock_resp.close) as mock_close:
            with patch.object(httpcore.ConnectionPool, "handle_request", return_value=mock_resp):
                with pytest.raises(SSRFResponseTooLargeError) as exc_info:
                    safe_fetch_url("https://www.example.edu/large", max_response_bytes=5242880)

                assert "exceeds maximum allowable limit of 5242880 bytes" in str(exc_info.value)
                mock_close.assert_called_once()


def test_safe_fetch_rejects_streaming_oversized_body_missing_content_length():
    """Verify streaming body exceeding limit without Content-Length is aborted and closed."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        # 3 chunks of 2 MiB = 6 MiB (exceeds 5 MiB limit)
        chunk_2mb = b"X" * (2 * 1024 * 1024)
        mock_resp = httpcore.Response(
            status=200,
            headers=[(b"content-type", b"application/octet-stream")],  # No Content-Length!
            content=[chunk_2mb, chunk_2mb, chunk_2mb],
        )
        with patch.object(mock_resp, "close", wraps=mock_resp.close) as mock_close:
            with patch.object(httpcore.ConnectionPool, "handle_request", return_value=mock_resp):
                with pytest.raises(SSRFResponseTooLargeError) as exc_info:
                    safe_fetch_url("https://www.example.edu/stream", max_response_bytes=5242880)

                assert "exceeded maximum limit of 5242880 bytes while downloading stream" in str(exc_info.value)
                mock_close.assert_called_once()


def test_safe_fetch_rejects_streaming_oversized_body_misleading_content_length():
    """Verify body exceeding limit with misleadingly small Content-Length is caught and closed."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        # Misleading Content-Length header claims 100 bytes, but stream sends 6 MiB
        chunk_2mb = b"X" * (2 * 1024 * 1024)
        mock_resp = httpcore.Response(
            status=200,
            headers=[(b"content-length", b"100")],
            content=[chunk_2mb, chunk_2mb, chunk_2mb],
        )
        with patch.object(mock_resp, "close", wraps=mock_resp.close) as mock_close:
            with patch.object(httpcore.ConnectionPool, "handle_request", return_value=mock_resp):
                with pytest.raises(SSRFResponseTooLargeError) as exc_info:
                    safe_fetch_url("https://www.example.edu/misleading", max_response_bytes=5242880)

                assert "exceeded maximum limit of 5242880 bytes while downloading stream" in str(exc_info.value)
                mock_close.assert_called_once()


def test_safe_fetch_allows_response_within_size_limit():
    """Verify response strictly within allowable body limit succeeds."""
    import httpcore

    with patch("backend.app.utils.ssrf.socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))
        ]

        payload = b"<html>Valid Scholarship Page</html>"
        mock_resp = httpcore.Response(
            status=200,
            headers=[(b"content-length", str(len(payload)).encode("ascii"))],
            content=payload,
        )
        with patch.object(httpcore.ConnectionPool, "handle_request", return_value=mock_resp):
            resp = safe_fetch_url("https://www.example.edu/valid", max_response_bytes=5242880)
            assert resp.status_code == 200
            assert resp.content == payload

