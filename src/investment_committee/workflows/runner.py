"""Run the planner and gatherers for one stock symbol."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from investment_committee.agents.planner import ResearchPlan, build_plan, normalize_symbol
from investment_committee.models import Evidence, Run, Source
from investment_committee.storage import DEFAULT_DB_PATH, open_db, save_run_with_evidence
from investment_committee.tools.earnings import EarningsDataError
from investment_committee.tools.market import MarketDataError
from investment_committee.workflows.chaining import (
    RawArticle,
    load_nlp,
    processed_to_evidence,
    run_chain,
)
from investment_committee.workflows.routing import (
    Gatherer,
    GathererResult,
    default_gatherers,
    route_plan,
)

# Provider errors that mean "this source has no data for the symbol", for
# example an ETF with no income statement. Other sources can still run.
MISSING_DATA_ERRORS = (EarningsDataError, MarketDataError)


@dataclass(frozen=True)
class ResearchSnapshot:
    """The plan and gathered results from one research run."""

    run: Run
    plan: ResearchPlan
    gathered: dict[Source, GathererResult]
    saved_evidence_count: int
    database_path: str | None
    storage_error: str | None
    gather_errors: dict[Source, str]


def _skip_missing_data(
    source: Source, gatherer: Gatherer, gather_errors: dict[Source, str]
) -> Gatherer:
    """Wrap a gatherer so a missing-data error becomes an empty result."""

    def gather(run: Run) -> GathererResult:
        try:
            return gatherer(run)
        except MISSING_DATA_ERRORS as error:
            gather_errors[source] = str(error)
            return []

    return gather


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
        The run, its plan, results from each gatherer, and the message for
        any source that had no data for the symbol.
    """
    normalized = normalize_symbol(symbol)
    run = Run(symbol=normalized)
    plan = build_plan(normalized)
    handlers = default_gatherers() if gatherers is None else gatherers
    gather_errors: dict[Source, str] = {}
    safe_handlers = {
        source: _skip_missing_data(source, handler, gather_errors)
        for source, handler in handlers.items()
    }
    gathered = route_plan(run, plan, gatherers=safe_handlers)
    # Earnings and market already emit shared Evidence records.  News emits
    # RawArticle objects because it still needs the NLP chain.  For the live
    # path (default gatherers), load the spaCy pipeline lazily and promote only
    # gate-approved news to the same shared Evidence pool.
    evidence = [
        item
        for source_results in gathered.values()
        for item in source_results
        if isinstance(item, Evidence)
    ]

    news_items = gathered.get("news", [])
    if news_items and all(isinstance(item, RawArticle) for item in news_items):
        nlp = load_nlp() if gatherers is None else None
        if nlp is not None:
            processed_news = run_chain(news_items, nlp)
            evidence.extend(processed_to_evidence(run, processed_news))

    saved_path: str | None = None
    saved_count = 0
    storage_error: str | None = None
    if database_path is not None:
        try:
            with closing(open_db(database_path)) as conn:
                save_run_with_evidence(conn, run, evidence)
        except (OSError, sqlite3.Error) as error:
            storage_error = str(error)
        else:
            saved_path = str(database_path)
            saved_count = len(evidence)

    return ResearchSnapshot(
        run=run,
        plan=plan,
        gathered=gathered,
        saved_evidence_count=saved_count,
        database_path=saved_path,
        storage_error=storage_error,
        gather_errors=gather_errors,
    )
