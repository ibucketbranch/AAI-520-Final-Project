"""Choosing a model server: OpenAI, a local server, or OpenRouter."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from investment_committee.agents.planner import CURRENT_OPENAI_MODELS, plan_research
from investment_committee.config import ENV_VARS, MissingKeyError, Settings

# ui_committee.py sits at the repo root next to app.py, outside the package.
sys.path.insert(0, str(Path(__file__).parents[1]))
from ui_committee import (  # noqa: E402
    ModelServer,
    model_servers,
    run_warnings,
    server_settings,
)


def settings_with(**values: str) -> Settings:
    """Build settings with every known variable unset except the given ones."""
    current = {name: None for name in ENV_VARS}
    current.update(values)
    return Settings(values=current)


def test_default_client_options_leave_the_openai_endpoint_alone():
    """Without OPENAI_BASE_URL no base_url is passed, so OpenAI runs stay as they were."""
    options = settings_with(OPENAI_API_KEY="key").openai_client_options()

    assert options == {"api_key": "key", "timeout": 30.0, "max_retries": 0}


def test_base_url_reaches_the_client_options():
    """A chosen server address must reach the client, or the run silently bills OpenAI."""
    options = settings_with(
        OPENAI_API_KEY="key", OPENAI_BASE_URL="http://local.test/v1"
    ).openai_client_options()

    assert options["base_url"] == "http://local.test/v1"


def test_client_options_still_require_a_key():
    """A missing key keeps raising MissingKeyError so callers can fall back as before."""
    with pytest.raises(MissingKeyError):
        settings_with().openai_client_options()


def test_with_values_copies_and_rejects_unknown_names():
    """Overrides must not leak into the shared settings, and typos must fail loudly."""
    original = settings_with(OPENAI_MODEL="first")
    changed = original.with_values(OPENAI_MODEL="second")

    assert original.values["OPENAI_MODEL"] == "first"
    assert changed.values["OPENAI_MODEL"] == "second"
    with pytest.raises(ValueError, match="OPENAI_MODLE"):
        original.with_values(OPENAI_MODLE="typo")


def test_planner_calls_the_chosen_server(monkeypatch):
    """The planner must build its client with the chosen base_url, not the default one."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.parse.side_effect = RuntimeError("stop after the client is built")
    openai_ctor = Mock(return_value=client)
    monkeypatch.setattr("investment_committee.agents.planner.OpenAI", openai_ctor)

    with pytest.raises(RuntimeError):
        plan_research(
            "AAPL",
            run_id="run",
            provider="openai",
            settings=settings_with(
                OPENAI_API_KEY="key", OPENAI_BASE_URL="http://local.test/v1", OPENAI_TIMEOUT="300"
            ),
        )

    openai_ctor.assert_called_once_with(
        api_key="key", timeout=300.0, max_retries=0, base_url="http://local.test/v1"
    )


def test_half_configured_servers_are_left_out_with_a_note():
    """A local server with no key must not show up as usable; the page says what is missing."""
    servers, notes = model_servers(settings_with(LOCAL_LLM_BASE_URL="http://local.test/v1"))

    assert servers == []
    assert notes == ["Local is left out because LOCAL_LLM_API_KEY is not set."]


def test_configured_servers_are_listed_with_billing_flags():
    """Local runs must not carry the billing warning; OpenAI and OpenRouter must."""
    servers, notes = model_servers(
        settings_with(
            OPENAI_API_KEY="openai-key",
            LOCAL_LLM_BASE_URL="http://local.test/v1",
            LOCAL_LLM_API_KEY="local-key",
            OPENROUTER_BASE_URL="http://router.test/v1",
            OPENROUTER_API_KEY="router-key",
        )
    )

    assert notes == []
    assert [(server.base_url, server.billed) for server in servers] == [
        (None, True),
        ("http://local.test/v1", False),
        ("http://router.test/v1", True),
    ]
    assert servers[0].known_models == CURRENT_OPENAI_MODELS
    assert servers[1].known_models is None


def test_server_settings_point_every_stage_at_one_server():
    """Planner, analysts, evaluator, and chair all read these four values."""
    server = ModelServer("Local", "http://local.test/v1", "local-key", billed=False)

    chosen = server_settings(settings_with(OPENAI_API_KEY="openai-key"), server, "gemma", 300)

    assert chosen.values["OPENAI_API_KEY"] == "local-key"
    assert chosen.values["OPENAI_BASE_URL"] == "http://local.test/v1"
    assert chosen.values["OPENAI_MODEL"] == "gemma"
    assert chosen.openai_timeout() == 300


def test_run_warnings_list_every_fallback():
    """A timed-out local model falls back quietly, so the page must say which stage did."""
    snapshot = SimpleNamespace(planner_fallback_reason="timed out")
    comparison = SimpleNamespace(
        with_review=SimpleNamespace(fallbacks={"bull": "timed out"}),
        without_review=SimpleNamespace(fallbacks={}),
    )

    assert run_warnings(snapshot, comparison) == [
        "Planner used the rule-based plan: timed out",
        "review on, bull: timed out",
    ]
