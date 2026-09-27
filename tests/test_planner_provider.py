"""Tests for selecting the planner provider without making network calls."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from investment_committee.agents.planner import (
    PlannedTasks,
    ResearchTask,
    plan_research,
)
from investment_committee.config import ENV_VARS, Settings
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


def test_openai_provider_returns_a_research_plan_and_model_call():
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
    assert client.responses.request["model"] == "test-model"
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
