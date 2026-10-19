"""Environment configuration for the investment committee.

Every credential the project uses is read here and nowhere else. Keys come
from the process environment, optionally topped up from a .env file via
python-dotenv. Components call Settings.require() for the key they need and
get a clear error naming the missing variable instead of a KeyError deep in
a tool call.
"""

from __future__ import annotations

import os
from math import isfinite
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

# Every environment variable the project may read, in .env.example order.
ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TIMEOUT",
    "OPENAI_BASE_URL",
    "LOCAL_LLM_BASE_URL",
    "LOCAL_LLM_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "NEWSAPI_KEY",
    "FRED_API_KEY",
)


class MissingKeyError(RuntimeError):
    """Raised when a component needs a key that is not set."""

    def __init__(self, name: str) -> None:
        """Build the error message for one missing variable.

        Args:
            name: The environment variable that was required but not set.
        """
        super().__init__(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or export {name} in the environment."
        )


class Settings(BaseModel):
    """A snapshot of the environment variables the project knows about.

    Values are never printed by any code in this package; callers report key
    names and set/missing status only.
    """

    values: dict[str, str | None]

    def openai_timeout(self) -> float:
        """Return the shared request timeout in seconds, defaulting to 30."""
        value = self.values.get("OPENAI_TIMEOUT") or "30"
        try:
            timeout = float(value)
        except ValueError as error:
            raise ValueError("OPENAI_TIMEOUT must be a positive number of seconds.") from error
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("OPENAI_TIMEOUT must be a positive number of seconds.")
        return timeout

    def openai_client_options(self) -> dict[str, Any]:
        """Return the keyword arguments every OpenAI client in the project uses.

        OPENAI_BASE_URL points the same client at any server that speaks the
        OpenAI API, such as a local Ollama or OpenRouter. It is passed only
        when set, so the default OpenAI endpoint is unchanged.

        Raises:
            MissingKeyError: If OPENAI_API_KEY is not set.
        """
        options: dict[str, Any] = {
            "api_key": self.require("OPENAI_API_KEY"),
            "timeout": self.openai_timeout(),
            "max_retries": 0,
        }
        base_url = self.values.get("OPENAI_BASE_URL")
        if base_url:
            options["base_url"] = base_url
        return options

    def with_values(self, **overrides: str | None) -> Settings:
        """Return a copy with some variables replaced, leaving this one as is.

        Args:
            **overrides: Variable names from ENV_VARS and their new values.

        Raises:
            ValueError: If a name is not one of ENV_VARS.
        """
        unknown = sorted(set(overrides) - set(ENV_VARS))
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(unknown)}")
        return Settings(values={**self.values, **overrides})

    def require(self, name: str) -> str:
        """Return the value of a required key or raise MissingKeyError.

        Args:
            name: An environment variable name from ENV_VARS.

        Returns:
            The non-empty value of the variable.

        Raises:
            MissingKeyError: If the variable is unset or empty.
        """
        value = self.values.get(name)
        if not value:
            raise MissingKeyError(name)
        return value

    def present(self) -> list[str]:
        """Return the names of the keys that are set, in ENV_VARS order."""
        return [name for name in ENV_VARS if self.values.get(name)]

    def missing(self) -> list[str]:
        """Return the names of the keys that are not set, in ENV_VARS order."""
        return [name for name in ENV_VARS if not self.values.get(name)]


def load_settings(dotenv_path: str | None = None) -> Settings:
    """Read the known environment variables into a Settings snapshot.

    Args:
        dotenv_path: Path to a .env file. When None, python-dotenv searches
            from the current directory upward; a missing file is a no-op.

    Returns:
        A Settings snapshot of the current environment.
    """
    load_dotenv(dotenv_path)
    return Settings(values={name: os.getenv(name) or None for name in ENV_VARS})
