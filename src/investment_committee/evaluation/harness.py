"""A/B harness: one evidence pool argued with and without the review loop.

Serves the Evaluation and Iteration notebook section. One gathering run is
the parent; the harness creates two committee runs pointing at it through
parent_run_id, so both arms argue from the identical pool and differ by
exactly one variable, run.with_review.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from investment_committee.agents.analyst import AnalystProvider
from investment_committee.config import Settings
from investment_committee.models import Run
from investment_committee.storage import load_run, save_run
from investment_committee.workflows.evaluator_optimizer import (
    CommitteeResult,
    run_committee_from_storage,
)


@dataclass(frozen=True)
class ReviewComparison:
    """Both arms of one A/B pair, argued from the same parent pool."""

    parent_run_id: str
    with_review: CommitteeResult
    without_review: CommitteeResult


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
