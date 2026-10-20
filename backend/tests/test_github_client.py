"""Deterministic unit tests for the public GitHub repository metadata client.

Verifies URL validation, SSRF boundary adherence, repository extraction,
and non-crashing behavior across HTTP 403, 404, SSRF blocks, and network failures.
All outbound HTTP operations are completely mocked; no real network calls are made.
"""

from unittest.mock import MagicMock
import httpx
import pytest

from backend.app.schemas import GitHubRepo
from backend.app.utils.github_client import (
    fetch_github_repos,
    parse_and_validate_github_username,
)
from backend.app.utils.ssrf import SSRFBlockedIPError


# ============================================================================
# Username & URL Parsing Tests
# ============================================================================

@pytest.mark.parametrize(
    "url, expected",
    [
        ("octocat", "octocat"),
        ("torvalds", "torvalds"),
        ("alice-researcher", "alice-researcher"),
        ("  valid-user-99  ", "valid-user-99"),
        ("@octocat", "octocat"),
        ("  @student-123  ", "student-123"),
        ("https://github.com/torvalds", "torvalds"),
        ("https://github.com/octocat/", "octocat"),
        ("http://github.com/alice-researcher", "alice-researcher"),
        ("https://www.github.com/ScholarSwarmDev1", "ScholarSwarmDev1"),
        ("  https://github.com/valid-user-99   ", "valid-user-99"),
    ],
)
def test_parse_and_validate_github_username_valid(url: str, expected: str):
    assert parse_and_validate_github_username(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "-leading-hyphen",
        "trailing-hyphen-",
        "double--hyphen",
        "invalid_special*chars",
        "user name with spaces",
        "a" * 40,  # exceeds 39 chars
        "@",
        "@-leading-hyphen",
        "@trailing-hyphen-",
        "@invalid_special*chars",
        "https://gitlab.com/octocat",
        "https://evil.com/github.com/octocat",
        "https://github.com/",
        "https://github.com/-leading-hyphen",
        "https://github.com/trailing-hyphen-",
        "https://github.com/invalid_special*chars",
        "https://user:password@github.com/octocat",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://github.com/" + "a" * 40,
        "not/a/url",
        "github.com/octocat",
    ],
)
def test_parse_and_validate_github_username_invalid(url: str):
    assert parse_and_validate_github_username(url) is None


# ============================================================================
# Repository Fetching Tests (Mocked Outbound Calls)
# ============================================================================

def test_fetch_github_repos_none_or_empty():
    repos, warnings = fetch_github_repos(None)
    assert repos == []
    assert warnings == []

    repos, warnings = fetch_github_repos("   ")
    assert repos == []
    assert warnings == []


def test_fetch_github_repos_invalid_url():
    repos, warnings = fetch_github_repos("https://notgithub.com/user")
    assert repos == []
    assert len(warnings) == 1
    assert "Invalid or unsupported GitHub profile URL" in warnings[0]


def test_fetch_github_repos_successful(monkeypatch):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "name": "scholarswarm-ai",
            "language": "Python",
            "stargazers_count": 42,
            "description": "Multi-agent scholarship discovery platform",
        },
        {
            "name": "fastapi-utils",
            "language": "TypeScript",
            "stargazers_count": 15,
            "description": None,
        },
    ]

    monkeypatch.setattr(
        "backend.app.utils.github_client.safe_fetch_url",
        lambda *args, **kwargs: mock_response,
    )

    repos, warnings = fetch_github_repos("https://github.com/teststudent")
    assert len(repos) == 2
    assert warnings == []
    assert isinstance(repos[0], GitHubRepo)
    assert repos[0].name == "scholarswarm-ai"
    assert repos[0].language == "Python"
    assert repos[0].stars == 42
    assert repos[0].description == "Multi-agent scholarship discovery platform"
    assert repos[1].name == "fastapi-utils"
    assert repos[1].stars == 15


def test_fetch_github_repos_handles_404_not_found(monkeypatch):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404

    monkeypatch.setattr(
        "backend.app.utils.github_client.safe_fetch_url",
        lambda *args, **kwargs: mock_response,
    )

    repos, warnings = fetch_github_repos("https://github.com/nonexistent-student-user")
    assert repos == []
    assert len(warnings) == 1
    assert "not found (HTTP 404)" in warnings[0]


def test_fetch_github_repos_handles_403_rate_limit(monkeypatch):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 403

    monkeypatch.setattr(
        "backend.app.utils.github_client.safe_fetch_url",
        lambda *args, **kwargs: mock_response,
    )

    repos, warnings = fetch_github_repos("https://github.com/rate-limited-user")
    assert repos == []
    assert len(warnings) == 1
    assert "rate limit exceeded or access forbidden" in warnings[0]


def test_fetch_github_repos_handles_ssrf_security_block(monkeypatch):
    def raise_ssrf(*args, **kwargs):
        raise SSRFBlockedIPError("IP address 10.0.0.1 is non-public")

    monkeypatch.setattr("backend.app.utils.github_client.safe_fetch_url", raise_ssrf)

    repos, warnings = fetch_github_repos("https://github.com/blocked-target")
    assert repos == []
    assert len(warnings) == 1
    assert "SSRF security policy blocked" in warnings[0]


def test_fetch_github_repos_handles_network_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Connection timed out after 5.0 seconds")

    monkeypatch.setattr("backend.app.utils.github_client.safe_fetch_url", raise_timeout)

    repos, warnings = fetch_github_repos("https://github.com/slow-endpoint")
    assert repos == []
    assert len(warnings) == 1
    assert "Network request to GitHub API failed" in warnings[0]


@pytest.mark.parametrize(
    "input_val, expected_username",
    [
        ("octocat", "octocat"),                        # 1. Bare username
        ("@octocat", "octocat"),                       # 2. Leading @ username
        ("https://github.com/octocat", "octocat"),     # 3. Full URL
        ("https://github.com/octocat/", "octocat"),    # 3b. Full URL with trailing slash
        ("http://github.com/torvalds", "torvalds"),    # 3c. HTTP URL
    ],
)
def test_fetch_github_repos_supported_formats_pass_exact_username_to_api(
    monkeypatch, input_val: str, expected_username: str
):
    """Explicitly verify bare usernames, @usernames, and full URLs pass the exact expected username to GitHub API."""
    captured_urls = []

    def mock_safe_fetch(url, **kwargs):
        captured_urls.append(url)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "name": f"{expected_username}-repo",
                "language": "Python",
                "stargazers_count": 100,
                "description": "Valid repository",
            }
        ]
        return mock_resp

    monkeypatch.setattr("backend.app.utils.github_client.safe_fetch_url", mock_safe_fetch)

    repos, warnings = fetch_github_repos(input_val)

    assert len(repos) == 1
    assert warnings == []
    assert repos[0].name == f"{expected_username}-repo"
    assert len(captured_urls) == 1
    expected_api_url = f"https://api.github.com/users/{expected_username}/repos?per_page=10&sort=updated"
    assert captured_urls[0] == expected_api_url


@pytest.mark.parametrize(
    "invalid_input",
    [
        "-leading-hyphen",
        "trailing-hyphen-",
        "invalid_special*chars",
        "user name",
        "@",
        "@-invalid",
        "https://gitlab.com/octocat",
        "https://evil.com/github.com/octocat",
        "file:///etc/passwd",
        "not/a/url",
        "https://github.com/",
    ],
)
def test_fetch_github_repos_invalid_inputs_never_call_api(monkeypatch, invalid_input: str):
    """Verify invalid usernames, foreign hosts, and invalid schemes never trigger outbound network requests."""
    api_called = False

    def mock_safe_fetch(*args, **kwargs):
        nonlocal api_called
        api_called = True
        return MagicMock()

    monkeypatch.setattr("backend.app.utils.github_client.safe_fetch_url", mock_safe_fetch)

    repos, warnings = fetch_github_repos(invalid_input)
    assert repos == []
    assert len(warnings) == 1
    assert "Invalid or unsupported GitHub profile URL" in warnings[0]
    assert not api_called, f"safe_fetch_url was unexpectedly called for invalid input '{invalid_input}'"
