"""Run the planner and gatherers for one stock symbol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from investment_committee.agents.planner import ResearchPlan, build_plan, normalize_symbol
from investment_committee.models import Run, Source
from investment_committee.workflows.routing import Gatherer, GathererResult, route_plan


@dataclass(frozen=True)
class ResearchSnapshot:
    """The plan and gathered results from one research run."""

    run: Run
    plan: ResearchPlan
    gathered: dict[Source, GathererResult]


def run_research(
    symbol: str,
    gatherers: Mapping[Source, Gatherer] | None = None,
) -> ResearchSnapshot:
    """Plan and gather the currently implemented research stages.

    Args:
        symbol: Stock symbol entered by the user.
        gatherers: Optional injected gatherers, mainly for offline tests.

    Returns:
        The run, its plan, and results from each gatherer.
    """
    normalized = normalize_symbol(symbol)
    run = Run(symbol=normalized)
    plan = build_plan(normalized)
    gathered = route_plan(run, plan, gatherers=gatherers)
    return ResearchSnapshot(run=run, plan=plan, gathered=gathered)
