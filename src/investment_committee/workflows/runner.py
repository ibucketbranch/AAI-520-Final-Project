"""Run the planner and gatherers for one stock symbol."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from investment_committee.agents.planner import ResearchPlan, build_plan, normalize_symbol
from investment_committee.models import Evidence, Run, Source
from investment_committee.storage import DEFAULT_DB_PATH, open_db, save_evidence, save_run
from investment_committee.workflows.routing import Gatherer, GathererResult, route_plan


@dataclass(frozen=True)
class ResearchSnapshot:
    """The plan and gathered results from one research run."""

    run: Run
    plan: ResearchPlan
    gathered: dict[Source, GathererResult]
    saved_evidence_count: int
    database_path: str | None


def run_research(
    symbol: str,
    gatherers: Mapping[Source, Gatherer] | None = None,
    database_path: str | Path | None = DEFAULT_DB_PATH,
) -> ResearchSnapshot:
    """Plan and gather the currently implemented research stages.

    Args:
        symbol: Stock symbol entered by the user.
        gatherers: Optional injected gatherers, mainly for offline tests.
        database_path: SQLite file to write, or None to skip persistence.

    Returns:
        The run, its plan, and results from each gatherer.
    """
    normalized = normalize_symbol(symbol)
    run = Run(symbol=normalized)
    plan = build_plan(normalized)
    gathered = route_plan(run, plan, gatherers=gatherers)
    evidence = [
        item
        for source_results in gathered.values()
        for item in source_results
        if isinstance(item, Evidence)
    ]

    saved_path = str(database_path) if database_path is not None else None
    if database_path is not None:
        with closing(open_db(database_path)) as conn:
            save_run(conn, run)
            save_evidence(conn, evidence)

    return ResearchSnapshot(
        run=run,
        plan=plan,
        gathered=gathered,
        saved_evidence_count=len(evidence) if database_path is not None else 0,
        database_path=saved_path,
    )
