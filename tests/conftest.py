"""Shared test setup.

Tests must pass with no .env present and must not depend on whatever keys
the developer's shell happens to export, so every known variable is cleared
and the working directory moves to a temp dir where python-dotenv finds no
.env file. Tests must not call the internet; mock every tool.
"""

import pytest

from investment_committee.config import ENV_VARS


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Clear known env vars and run each test from an empty temp directory."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
