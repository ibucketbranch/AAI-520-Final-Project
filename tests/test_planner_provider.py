"""Tests for selecting the planner provider without making network calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai import APIError
from pydantic import ValidationError

from investment_committee.agents.planner import (
    PlannedTasks,
    PlannerProviderError,
    ResearchTask,
    list_planner_models,
    plan_research,
)
from investment_committee.config import ENV_VARS, MissingKeyError, Settings
from investment_committee.models import MemoryNote


class FakeResponses:
    """Return one fixed structured plan."""

    def __init__(self):
        self.request = None

    def parse(self, **request):
        self.request = request
        return SimpleNamespace(
            output_parsed=PlannedTasks(
                tasks=[
                    ResearchTask(
                        source="news",
                        reason="Check recent events before reviewing the numbers.",
                    ),
                    ResearchTask(
                        source="earnings",
                        reason="Review the latest quarterly results.",
                    ),
                ]
            ),
            model="test-openai-model",
            usage=SimpleNamespace(input_tokens=80, output_tokens=25),
        )


class FakeClient:
    """Small stand-in for the part of the OpenAI client used by the planner."""

    def __init__(self):
        self.responses = FakeResponses()


def settings_with(**values):
    """Build settings without loading the developer's local .env file."""
    current = {name: None for name in ENV_VARS}
    current.update(values)
    return Settings(values=current)


@pytest.mark.parametrize(
    ("selected_model", "expected_model"), [(None, "test-model"), ("chosen-model", "chosen-model")]
)
def test_openai_provider_returns_a_research_plan_and_model_call(selected_model, expected_model):
    client = FakeClient()
    note = MemoryNote(
        run_id="old-run",
        symbol="AAPL",
        confidence=0.6,
        open_gaps=["Check recent news"],
        lesson="Start with news next time.",
    )

    result = plan_research(
        " aapl ",
        run_id="new-run",
        provider="openai",
        previous_note=note,
        settings=settings_with(OPENAI_API_KEY="test-key", OPENAI_MODEL="test-model"),
        client=client,
        model=selected_model,
    )

    assert result.plan.symbol == "AAPL"
    assert [task.source for task in result.plan.tasks] == ["news", "earnings"]
    assert result.plan.memory_lesson == "Start with news next time."
    assert result.provider_used == "openai"
    assert result.fallback_reason is None
    assert result.model_call is not None
    assert result.model_call.run_id == "new-run"
    assert result.model_call.model == "test-openai-model"
    assert result.model_call.prompt_tokens == 80
    assert result.model_call.completion_tokens == 25
    assert client.responses.request["model"] == expected_model
    assert client.responses.request["text_format"] is PlannedTasks


def test_openai_provider_falls_back_when_the_key_is_missing():
    result = plan_research(
        "AAPL",
        run_id="new-run",
        provider="openai",
        settings=settings_with(),
    )

    assert result.provider_requested == "openai"
    assert result.provider_used == "rules"
    assert result.fallback_reason is not None
    assert "OPENAI_API_KEY" in result.fallback_reason
    assert [task.source for task in result.plan.tasks] == ["earnings", "news", "market"]


def test_rule_based_provider_does_not_need_a_key():
    result = plan_research(
        "AAPL",
        run_id="new-run",
        provider="rules",
        settings=settings_with(),
    )

    assert result.provider_used == "rules"
    assert result.fallback_reason is None


def test_provider_failure_falls_back_to_the_rule_based_plan():
    class BrokenResponses:
        def parse(self, **request):
            raise RuntimeError("service unavailable")

    broken_client = SimpleNamespace(responses=BrokenResponses())
    result = plan_research(
        "AAPL",
        run_id="new-run",
        provider="openai",
        settings=settings_with(OPENAI_API_KEY="test-key"),
        client=broken_client,
    )

    assert result.provider_used == "rules"
    assert result.fallback_reason == "OpenAI could not create a research plan."


def test_openai_provider_uses_budgeted_owned_client_context(monkeypatch):
    from unittest.mock import MagicMock

    owned_client = MagicMock()
    owned_client.__enter__.return_value = owned_client
    owned_client.responses.parse.return_value = SimpleNamespace(
        output_parsed=PlannedTasks(
            tasks=[
                ResearchTask(source="news", reason="Check recent events."),
                ResearchTask(source="market", reason="Check current trend."),
            ]
        ),
        model="test-openai-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    openai_ctor = Mock(return_value=owned_client)
    monkeypatch.setattr("investment_committee.agents.planner.OpenAI", openai_ctor)

    result = plan_research(
        "AAPL",
        run_id="new-run",
        provider="openai",
        settings=settings_with(OPENAI_API_KEY="test-key"),
    )

    assert result.provider_used == "openai"
    openai_ctor.assert_called_once_with(api_key="test-key", timeout=10, max_retries=0)
    owned_client.__enter__.assert_called_once()
    owned_client.__exit__.assert_called_once()


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown planner provider"):
        plan_research("AAPL", run_id="new-run", provider="other")  # type: ignore[arg-type]


def test_model_plan_rejects_the_same_source_twice():
    with pytest.raises(ValidationError, match="only once"):
        PlannedTasks(
            tasks=[
                ResearchTask(source="news", reason="First"),
                ResearchTask(source="news", reason="Again"),
            ]
        )


@pytest.fixture()
def model_client(monkeypatch):
    from unittest.mock import MagicMock

    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr("investment_committee.agents.planner.OpenAI", Mock(return_value=client))
    return client


def test_model_list_shows_only_current_aliases_available_in_the_catalog(model_client):
    names = [
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-6-luna",
        "gpt-6-astra-2026-09-01",
        "gpt-5.6-sol",
        "gpt-4.1-mini",
        "gpt-4.1-mini",
        "o3-mini",
        "o1-mini",
        "gpt-4o-2024-05-13",
        "gpt-4o-2024-08-06",
        "gpt-4o-mini-transcribe",
        "gpt-4o-mini-tts",
        "gpt-4o-mini-search-preview",
        "gpt-5-chat-latest",
        "gpt-5.3-codex",
        "text-embedding-3-small",
        "gpt-image-2",
        "gpt-3.5-turbo",
    ]
    model_client.models.list.return_value = [SimpleNamespace(id=name) for name in names]

    models = list_planner_models("openai", settings_with(OPENAI_API_KEY="test-key"))

    assert models == ["gpt-6-luna", "gpt-6-sol"]
    model_client.models.list.assert_called_once()


def test_model_list_reports_connection_errors(model_client):
    model_client.models.list.side_effect = APIError("unavailable", request=Mock(), body=None)
    with pytest.raises(PlannerProviderError, match="Could not load OpenAI models"):
        list_planner_models("openai", settings_with(OPENAI_API_KEY="test-key"))


@pytest.mark.parametrize("names", [[], ["whisper-1"], ["gpt-5.6-sol", "gpt-4.1-mini"]])
def test_model_list_reports_no_matching_models(model_client, names):
    model_client.models.list.return_value = [SimpleNamespace(id=name) for name in names]
    with pytest.raises(PlannerProviderError, match="no current planner models"):
        list_planner_models("openai", settings_with(OPENAI_API_KEY="test-key"))


def test_rule_based_model_list_needs_no_key_or_request(model_client):
    assert list_planner_models("rules", settings_with()) == []
    model_client.models.list.assert_not_called()


def test_model_list_requires_a_key_and_rejects_unknown_providers(model_client):
    with pytest.raises(MissingKeyError):
        list_planner_models("openai", settings_with())
    with pytest.raises(ValueError, match="Unknown planner provider"):
        list_planner_models("other", settings_with())
    model_client.models.list.assert_not_called()
