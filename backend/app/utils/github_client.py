"""Public GitHub repository metadata client for ScholarSwarm AI.

Safely fetches repository metadata for verified student profiles via GitHub's public API.
Enforces SSRF prevention, strict URL/username validation, non-crashing failure modes,
and mapping into canonical GitHubRepo schema models.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from backend.app.schemas import GitHubRepo
from backend.app.utils.ssrf import (
    SSRFSecurityError,
    safe_fetch_url,
)


GITHUB_USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")
ALLOWED_GITHUB_HOSTS = {"github.com", "www.github.com"}


def parse_and_validate_github_username(url_str: str) -> Optional[str]:
    """Extract and validate GitHub username from a public profile URL or username.

    Accepts forms such as:
    - octocat
    - @octocat
    - https://github.com/octocat
    - https://github.com/octocat/
    - http://github.com/octocat
    - https://www.github.com/octocat

    Rejects invalid schemes, non-github hosts, embedded credentials, path traversals,
    and invalid username characters.
    """
    if not url_str or not isinstance(url_str, str):
        return None

    clean_url = url_str.strip()

    # Form A: Username starting with @ (e.g. "@octocat")
    if clean_url.startswith("@"):
        candidate = clean_url[1:].strip()
        if GITHUB_USERNAME_REGEX.match(candidate):
            return candidate
        return None

    # Form B: URL structure (contains scheme :// or path /)
    if "://" in clean_url or "/" in clean_url:
        try:
            parts = urlsplit(clean_url)
        except Exception:
            return None

        if parts.scheme.lower() not in ("http", "https"):
            return None

        if parts.username or parts.password:
            return None

        host = (parts.hostname or "").lower()
        if host not in ALLOWED_GITHUB_HOSTS:
            return None

        # Path should start with /<username>
        path_segments = [seg for seg in parts.path.split("/") if seg]
        if not path_segments:
            return None

        username = path_segments[0]
        if not GITHUB_USERNAME_REGEX.match(username):
            return None

        return username

    # Form C: Bare username (e.g. "octocat", "torvalds")
    if GITHUB_USERNAME_REGEX.match(clean_url):
        return clean_url

    return None


def fetch_github_repos(
    github_url: Optional[str],
    timeout: float = 5.0,
) -> Tuple[List[GitHubRepo], List[str]]:
    """Retrieve public repository metadata for a given GitHub profile URL.

    Guarantees:
    - Outbound API call reuses SSRF-safe DNS pinning and IP validation.
    - Zero external calls made if URL is absent or invalid.
    - Never raises uncaught exceptions; errors and rate limits return empty lists
      with informative warning messages.
    - Caps results to top 10 repositories.
    """
    if not github_url or not github_url.strip():
        return [], []

    raw_url = github_url.strip()
    username = parse_and_validate_github_username(raw_url)
    if not username:
        return [], [f"Invalid or unsupported GitHub profile URL: '{raw_url}'."]

    api_url = f"https://api.github.com/users/{username}/repos?per_page=10&sort=updated"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ScholarSwarm-Agent/1.0 (+https://scholarswarm.internal)",
    }

    try:
        response = safe_fetch_url(
            url=api_url,
            method="GET",
            headers=headers,
            timeout=timeout,
            max_redirects=2,
        )
    except SSRFSecurityError as exc:
        return [], [f"SSRF security policy blocked GitHub request for '{username}': {exc}"]
    except Exception as exc:
        return [], [f"Network request to GitHub API failed for user '{username}': {exc}"]

    if response.status_code == 200:
        try:
            data = response.json()
            if not isinstance(data, list):
                return [], [f"Unexpected payload format from GitHub API for user '{username}'."]

            repos: List[GitHubRepo] = []
            for item in data[:10]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not name or not isinstance(name, str):
                    continue
                repos.append(
                    GitHubRepo(
                        name=name,
                        language=item.get("language") if isinstance(item.get("language"), str) else None,
                        stars=item.get("stargazers_count", 0) if isinstance(item.get("stargazers_count"), int) else 0,
                        description=item.get("description") if isinstance(item.get("description"), str) else None,
                    )
                )
            return repos, []
        except Exception as exc:
            return [], [f"Failed to parse GitHub API response for user '{username}': {exc}"]

    if response.status_code == 404:
        return [], [f"GitHub user '{username}' not found (HTTP 404)."]

    if response.status_code in (403, 429):
        return [], [f"GitHub API rate limit exceeded or access forbidden (HTTP {response.status_code})."]

    return [], [f"GitHub API returned unexpected status {response.status_code} for user '{username}'."]
