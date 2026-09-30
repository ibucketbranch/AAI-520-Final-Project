"""Metrics for the final notebook's results table.

Counts supported vs unsupported claims per run so the team can compare runs
with and without the evaluator loop. The measuring-and-charting harness
lives with the evaluation owner; these helpers are the storage-reading seam
both lanes share, so the harness and the notebook compute the same numbers
from the same rows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from investment_committee.models import Claim
from investment_committee.storage import load_claims, load_run


def supported_share(claims: list[Claim]) -> float:
    """Return the share of claims marked supported; 0.0 for an empty list."""
    if not claims:
        return 0.0
    supported = sum(1 for claim in claims if claim.supported)
    return supported / len(claims)


@dataclass(frozen=True)
class RunMetrics:
    """One run's claim counts, the row the comparison table is built from."""

    run_id: str
    symbol: str
    with_review: bool
    claims: int
    supported: int
    unsupported: int
    supported_share: float


def run_metrics(conn: sqlite3.Connection, run_id: str) -> RunMetrics:
    """Compute one run's metrics from its stored claims.

    Args:
        conn: An open connection from storage.open_db().
        run_id: The run to measure.

    Returns:
        The counts over every stored claim revision for the run.

    Raises:
        ValueError: If the run_id is not in the database.
    """
    run = load_run(conn, run_id)
    if run is None:
        raise ValueError(f"No run with id {run_id} in the database.")
    claims = load_claims(conn, run_id)
    supported = sum(1 for claim in claims if claim.supported)
    unsupported = sum(1 for claim in claims if claim.supported is False)
    return RunMetrics(
        run_id=run.run_id,
        symbol=run.symbol,
        with_review=run.with_review,
        claims=len(claims),
        supported=supported,
        unsupported=unsupported,
        supported_share=supported_share(claims),
    )


def comparison_rows(conn: sqlite3.Connection, run_ids: list[str]) -> list[RunMetrics]:
    """Compute metrics for several runs, in the order given.

    The with/without-review comparison passes the paired run ids here and
    charts the result; each row says which arm it belongs to via
    with_review.
    """
    return [run_metrics(conn, run_id) for run_id in run_ids]
