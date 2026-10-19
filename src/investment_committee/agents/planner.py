"""Planner agent: decides what to gather for a stock symbol.

Given a ticker, plans the research steps and dispatches the earnings, news,
and market gatherers. Reads the memory note from the previous run before
planning. Serves the "plans its research steps" agent function.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from openai import APIError, OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError, field_validator

from investment_committee.config import MissingKeyError, Settings, load_settings
from investment_committee.models import MemoryNote, ModelCall, Source

_SOURCE_ORDER: tuple[Source, ...] = ("earnings", "news", "market")
_REASONS: dict[Source, str] = {
    "earnings": "Collect the latest quarterly performance.",
    "news": "Collect recent events that may affect the company.",
    "market": "Collect recent price history and market indicators.",
}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")

PlannerProvider = Literal["openai", "rules"]
DEFAULT_PLANNER_PROVIDER: PlannerProvider = "openai"
DEFAULT_OPENAI_MODEL = "gpt-6-luna"
# Current model aliases; dated snapshots and older generations stay out of the menu.
CURRENT_OPENAI_MODELS = ("gpt-6-luna", "gpt-6-sol", "gpt-6-astra")


class PlannerProviderError(RuntimeError):
    """Raised when a planner provider cannot return a usable plan."""


class ResearchTask(BaseModel):
    """One source the planner asks a gatherer to research."""

    source: Source
    reason: str = Field(min_length=1)


class ResearchPlan(BaseModel):
    """The ordered gatherer work for one stock symbol."""

    symbol: str
    tasks: list[ResearchTask] = Field(min_length=1)
    memory_lesson: str | None = None


class PlannedTasks(BaseModel):
    """Tasks returned by a model before the final plan is built."""

    tasks: list[ResearchTask] = Field(min_length=1, max_length=3)

    @field_validator("tasks")
    @classmethod
    def sources_must_be_unique(cls, tasks: list[ResearchTask]) -> list[ResearchTask]:
        """Reject a plan that asks for the same source twice."""
        sources = [task.source for task in tasks]
        if len(sources) != len(set(sources)):
            raise ValueError("Each research source can appear only once.")
        return tasks


@dataclass(frozen=True)
class PlanningResult:
    """A plan plus details about how it was created."""

    plan: ResearchPlan
    provider_requested: PlannerProvider
    provider_used: PlannerProvider
    fallback_reason: str | None = None
    model_call: ModelCall | None = None


def list_planner_models(provider: PlannerProvider, settings: Settings | None = None) -> list[str]:
    """Return current planner models available to this API key."""
    if provider == "rules":
        return []
    if provider != "openai":
        raise ValueError(f"Unknown planner provider: {provider}")

    current_settings = settings or load_settings()
    options = current_settings.openai_client_options()
    try:
        with OpenAI(**options) as client:
            available = {model.id for model in client.models.list()}
    except APIError as error:
        raise PlannerProviderError(
            "Could not load OpenAI models. Check the API key and connection."
        ) from error

    models = [model for model in CURRENT_OPENAI_MODELS if model in available]
    if not models:
        raise PlannerProviderError("OpenAI returned no current planner models for this key.")
    return models


def normalize_symbol(symbol: str) -> str:
    """Return a normalized ticker or raise for an invalid value.

    Args:
        symbol: User-entered stock symbol.

    Returns:
        The uppercase symbol with surrounding whitespace removed.

    Raises:
        ValueError: If the value is blank or not shaped like a ticker.
    """
    normalized = symbol.strip().upper()
    if not _SYMBOL.fullmatch(normalized):
        raise ValueError(f"Invalid stock symbol: {symbol!r}")
    return normalized


def build_plan(symbol: str, previous_note: MemoryNote | None = None) -> ResearchPlan:
    """Create the deterministic v1 research plan.

    A source mentioned in the previous run's open gaps moves to the front of
    the plan. This makes the memory handoff observable while keeping the
    Module 4 walking skeleton independent of an LLM.

    Args:
        symbol: Stock symbol to research.
        previous_note: Most recent note for this symbol, when one exists.

    Returns:
        An ordered plan containing earnings, news, and market tasks.

    Raises:
        ValueError: If the symbol is invalid or the note belongs to another
            symbol.
    """
    normalized = normalize_symbol(symbol)
    if previous_note is not None and normalize_symbol(previous_note.symbol) != normalized:
        raise ValueError("The memory note belongs to a different stock symbol.")

    gaps = [gap.casefold() for gap in previous_note.open_gaps] if previous_note else []
    prioritized = [source for source in _SOURCE_ORDER if any(source in gap for gap in gaps)]
    ordered = prioritized + [source for source in _SOURCE_ORDER if source not in prioritized]

    tasks = [
        ResearchTask(
            source=source,
            reason=(
                f"Revisit the {source} gap reported by the previous run."
                if source in prioritized
                else _REASONS[source]
            ),
        )
        for source in ordered
    ]
    return ResearchPlan(
        symbol=normalized,
        tasks=tasks,
        memory_lesson=previous_note.lesson if previous_note else None,
    )


def _openai_prompt(symbol: str, previous_note: MemoryNote | None) -> str:
    """Build the stock-specific part of the OpenAI prompt."""
    if previous_note is None:
        memory = "There is no note from an earlier run."
    else:
        memory = json.dumps(
            {
                "lesson": previous_note.lesson,
                "open_gaps": previous_note.open_gaps,
                "confidence": previous_note.confidence,
            }
        )

    return (
        f"Plan the research for stock symbol {symbol}.\n"
        "Available sources are earnings, news, and market. Choose one to three sources "
        "and put the most useful source first. Give a short reason for each choice.\n"
        f"Previous run information: {memory}"
    )


def _build_openai_plan(
    symbol: str,
    run_id: str,
    previous_note: MemoryNote | None,
    settings: Settings,
    client: Any | None,
    model: str | None,
) -> PlanningResult:
    """Ask OpenAI for ordered research tasks."""
    options = settings.openai_client_options()
    model = model or settings.values.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    openai_client_cm = nullcontext(client) if client is not None else OpenAI(**options)
    instructions = (
        "You are the planner for a student investment research project. "
        "Return only a small research plan using the available sources."
    )
    prompt = _openai_prompt(symbol, previous_note)
    started = perf_counter()

    try:
        with openai_client_cm as openai_client:
            response = openai_client.responses.parse(
                model=model,
                instructions=instructions,
                input=prompt,
                text_format=PlannedTasks,
            )
    except (OpenAIError, ValidationError) as error:
        raise PlannerProviderError("OpenAI could not create a research plan.") from error

    parsed = response.output_parsed
    if parsed is None:
        raise PlannerProviderError("OpenAI returned an empty research plan.")

    plan = ResearchPlan(
        symbol=symbol,
        tasks=parsed.tasks,
        memory_lesson=previous_note.lesson if previous_note else None,
    )
    usage = getattr(response, "usage", None)
    model_call = ModelCall(
        run_id=run_id,
        stage="planner",
        model=getattr(response, "model", model),
        prompt=f"{instructions}\n\n{prompt}",
        response=plan.model_dump_json(indent=2),
        prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
        completion_tokens=getattr(usage, "output_tokens", 0) or 0,
        latency_ms=round((perf_counter() - started) * 1000),
    )
    return PlanningResult(
        plan=plan,
        provider_requested="openai",
        provider_used="openai",
        model_call=model_call,
    )


def plan_research(
    symbol: str,
    run_id: str,
    provider: PlannerProvider = DEFAULT_PLANNER_PROVIDER,
    previous_note: MemoryNote | None = None,
    settings: Settings | None = None,
    client: Any | None = None,
    model: str | None = None,
) -> PlanningResult:
    """Build a research plan with the selected provider.

    OpenAI is the default. If its key is missing or the request fails, the
    existing rule-based planner keeps the research run usable. A selected
    model overrides OPENAI_MODEL; leaving it out uses the configured default.
    """
    normalized = normalize_symbol(symbol)

    if provider == "rules":
        return PlanningResult(
            plan=build_plan(normalized, previous_note),
            provider_requested="rules",
            provider_used="rules",
        )
    if provider != "openai":
        raise ValueError(f"Unknown planner provider: {provider}")

    current_settings = settings or load_settings()
    try:
        return _build_openai_plan(
            normalized,
            run_id,
            previous_note,
            current_settings,
            client,
            model,
        )
    except (MissingKeyError, PlannerProviderError) as error:
        return PlanningResult(
            plan=build_plan(normalized, previous_note),
            provider_requested="openai",
            provider_used="rules",
            fallback_reason=str(error),
        )
