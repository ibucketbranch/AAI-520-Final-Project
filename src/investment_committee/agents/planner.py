"""Planner agent: decides what to gather for a stock symbol.

Given a ticker, plans the research steps and dispatches the earnings, news,
and market gatherers. Reads the memory note from the previous run before
planning. Serves the "plans its research steps" agent function.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from investment_committee.models import MemoryNote, Source

_SOURCE_ORDER: tuple[Source, ...] = ("earnings", "news", "market")
_REASONS: dict[Source, str] = {
    "earnings": "Collect the latest quarterly performance.",
    "news": "Collect recent events that may affect the company.",
    "market": "Collect recent price history and market indicators.",
}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


class ResearchTask(BaseModel):
    """One source the planner asks a gatherer to research."""

    source: Source
    reason: str


class ResearchPlan(BaseModel):
    """The ordered gatherer work for one stock symbol."""

    symbol: str
    tasks: list[ResearchTask] = Field(min_length=1)
    memory_lesson: str | None = None


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
