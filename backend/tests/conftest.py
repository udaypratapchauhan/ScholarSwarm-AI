"""Pytest test configuration and environment isolation.

Ensures the automated test suite runs hermetically with mock providers
so unit tests do not exhaust live API keys or depend on external internet access.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def hermetic_test_environment(monkeypatch: pytest.MonkeyPatch):
    """Ensure tests run hermetically with mock search provider by default."""
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    monkeypatch.setenv("SEARCH_API_KEY", "")
