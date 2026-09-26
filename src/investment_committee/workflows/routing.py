"""Routing workflow: send content to the right specialist.

Directs each piece of gathered content to the earnings, news, or market
analyzer. Serves the Routing workflow pattern.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from investment_committee.agents.planner import ResearchPlan, normalize_symbol
from investment_committee.models import Evidence, Run, Source
from investment_committee.tools.earnings import gather_earnings
from investment_committee.tools.market import gather_market
from investment_committee.tools.news import gather_news
from investment_committee.workflows.chaining import RawArticle

GathererResult = list[Evidence] | list[RawArticle]
Gatherer = Callable[[Run], GathererResult]


def default_gatherers() -> dict[Source, Gatherer]:
    """Return the production gatherer mapped to each planner source."""
    return {
        "earnings": gather_earnings,
        "news": gather_news,
        "market": gather_market,
    }


def route_plan(
    run: Run,
    plan: ResearchPlan,
    gatherers: Mapping[Source, Gatherer] | None = None,
) -> dict[Source, GathererResult]:
    """Dispatch each plan task to its source-specific gatherer.

    The news result is a list of RawArticle objects for Mina's chain. Market
    and earnings results are already Evidence. The walking-skeleton
    orchestrator can therefore show the handoff without coupling the router
    to news preprocessing.

    Args:
        run: Research run passed to every gatherer.
        plan: Ordered tasks produced by the planner.
        gatherers: Optional injected handlers; defaults to the live tools.

    Returns:
        Results keyed by source, preserving the plan's insertion order.

    Raises:
        ValueError: If the run and plan symbols differ or a source is listed
            more than once.
        KeyError: If no gatherer was supplied for a planned source.
    """
    if normalize_symbol(run.symbol) != plan.symbol:
        raise ValueError("The research run and plan use different stock symbols.")

    routed_run = run.model_copy(update={"symbol": plan.symbol})
    handlers = default_gatherers() if gatherers is None else gatherers
    results: dict[Source, GathererResult] = {}
    for task in plan.tasks:
        if task.source in results:
            raise ValueError(f"The plan contains duplicate {task.source} tasks.")
        handler = handlers.get(task.source)
        if handler is None:
            raise KeyError(f"No gatherer configured for {task.source}.")
        results[task.source] = handler(routed_run)
    return results
