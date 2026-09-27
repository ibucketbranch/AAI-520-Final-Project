"""Environment configuration for the investment committee.

Every credential the project uses is read here and nowhere else. Keys come
from the process environment, optionally topped up from a .env file via
python-dotenv. Components call Settings.require() for the key they need and
get a clear error naming the missing variable instead of a KeyError deep in
a tool call.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel

# Every environment variable the project may read, in .env.example order.
ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "NEWSAPI_KEY",
    "FRED_API_KEY",
    "DATABASE_URL",
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
