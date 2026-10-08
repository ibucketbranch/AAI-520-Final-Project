"""A/B harness: one evidence pool argued with and without the review loop.

One gathering run is the parent. The harness creates two committee runs that
point to it through parent_run_id, so both arms use the same evidence and the
only changed setting is run.with_review.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from investment_committee.agents.analyst import AnalystProvider
from investment_committee.agents.planner import PlannerProvider
from investment_committee.config import Settings
from investment_committee.evaluation.metrics import RunScore, comparison_rows
from investment_committee.models import Run, Source
from investment_committee.storage import load_run, open_db, save_run
from investment_committee.workflows.evaluator_optimizer import (
    CommitteeResult,
    run_committee_from_storage,
)
from investment_committee.workflows.routing import Gatherer
from investment_committee.workflows.runner import run_research

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


@dataclass(frozen=True)
class ReviewComparison:
    """Both arms of one A/B pair, argued from the same parent pool."""

    parent_run_id: str
    with_review: CommitteeResult
    without_review: CommitteeResult


def plot_support_comparison(scores: Sequence[RunScore]) -> tuple[Figure, Axes]:
    """Plot supported claims and rejected drafts from stored committee runs."""
    import matplotlib.pyplot as plt

    labels = [
        f"{score.symbol}\n{'with review' if score.with_review else 'without review'}"
        for score in scores
    ]
    supported = [score.claims_supported for score in scores]
    rejected = [score.claims_rejected for score in scores]

    figure, axis = plt.subplots(figsize=(10, 5))
    positions = list(range(len(scores)))
    width = 0.38
    axis.bar([p - width / 2 for p in positions], supported, width, label="Supported")
    axis.bar([p + width / 2 for p in positions], rejected, width, label="Rejected drafts")
    axis.set_xticks(positions, labels)
    axis.set_ylabel("Claim count")
    axis.set_title("Claim support with and without review")
    axis.legend()
    figure.tight_layout()
    return figure, axis


def run_review_comparison(
    conn: sqlite3.Connection,
    parent_run_id: str,
    settings: Settings | None = None,
    *,
    provider: AnalystProvider = "openai",
    max_rounds: int = 2,
    model: str | None = None,
    client: Any | None = None,
) -> ReviewComparison:
    """Deliberate one gathering run twice: with the review loop, then without.

    Args:
        conn: An open connection from open_db().
        parent_run_id: The gathering run whose evidence both arms argue from.
        settings: Loaded settings, or None to read the environment.
        provider: Analyst provider, "openai" or the offline "template".
        max_rounds: Round cap for the with-review arm.
        model: Model override, or None for the configured default.
        client: Injected API client, mainly for offline tests.

    Returns:
        Both deliberations; each one is already persisted by the time this
        returns, so the metrics can read them back from the same database.

    Raises:
        ValueError: If the parent run is not in this database.
    """
    parent = load_run(conn, parent_run_id)
    if parent is None:
        raise ValueError(f"run {parent_run_id!r} is not in this database; gather or seed it first")
    results: dict[bool, CommitteeResult] = {}
    for with_review in (True, False):
        run = Run(symbol=parent.symbol, with_review=with_review, parent_run_id=parent_run_id)
        save_run(conn, run)
        results[with_review] = run_committee_from_storage(
            conn,
            run.run_id,
            settings,
            provider=provider,
            max_rounds=max_rounds,
            model=model,
            client=client,
        )
    return ReviewComparison(
        parent_run_id=parent_run_id,
        with_review=results[True],
        without_review=results[False],
    )


def run_symbol_sweep(
    symbols: Sequence[str],
    database_path: str | Path,
    settings: Settings | None = None,
    *,
    gatherers: Mapping[Source, Gatherer] | None = None,
    planner_provider: PlannerProvider = "openai",
    provider: AnalystProvider = "openai",
    max_rounds: int = 2,
    model: str | None = None,
    client: Any | None = None,
) -> list[dict[str, object]]:
    """Gather and deliberate each symbol both ways; return the full table.

    One gathering run per symbol, then both review arms off it through
    run_review_comparison, scored from storage with comparison_rows. The
    result is the Evaluation section's table over every symbol, two rows
    per symbol, in input order.

    Args:
        symbols: The symbols to sweep, in display order.
        database_path: SQLite file shared by every run in the sweep.
        settings: Loaded settings, or None to read the environment.
        gatherers: Injected gatherers for offline tests. None takes the
            runner's default path, the only path that engages the news
            chain and gate.
        planner_provider: Planner for the gathering runs.
        provider: Analyst provider for the deliberations.
        max_rounds: Round cap for the with-review arms.
        model: Model override, or None for the configured default.
        client: Injected API client, mainly for offline tests.

    Returns:
        comparison_rows output for all arms, two rows per symbol.
    """
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        snapshot = run_research(
            symbol,
            gatherers=gatherers,
            database_path=database_path,
            planner_provider=planner_provider,
        )
        with closing(open_db(database_path)) as conn:
            comparison = run_review_comparison(
                conn,
                snapshot.run.run_id,
                settings,
                provider=provider,
                max_rounds=max_rounds,
                model=model,
                client=client,
            )
            rows.extend(
                comparison_rows(
                    conn,
                    [
                        comparison.with_review.run.run_id,
                        comparison.without_review.run.run_id,
                    ],
                )
            )
    return rows
