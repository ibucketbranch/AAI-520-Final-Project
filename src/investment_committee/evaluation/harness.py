"""Small evaluation harness for the final notebook.

The lightweight harness keeps orchestration separate from plotting. It can run
the same symbols through the same claim generator with the evaluator loop
disabled and enabled, then return a tidy list suitable for pandas and
matplotlib. The storage-backed harness points both complete committee runs at
one parent evidence pool through parent_run_id.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from investment_committee.agents.analyst import AnalystProvider
from investment_committee.config import Settings
from investment_committee.evaluation.metrics import (
    MetricsRow,
    ReviewMetrics,
    compare_conditions,
    metrics_to_rows,
)
from investment_committee.models import Claim, Evidence, Run
from investment_committee.storage import load_run, save_run
from investment_committee.workflows.evaluator_optimizer import (
    CommitteeResult,
    run_committee_from_storage,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

ClaimFactory = Callable[[Run, list[Evidence]], list[Claim]]


@dataclass(frozen=True)
class ReviewComparison:
    """Both arms of one A/B pair, argued from the same parent pool."""

    parent_run_id: str
    with_review: CommitteeResult
    without_review: CommitteeResult


def _bind_evidence(
    claim_factory: ClaimFactory, evidence: list[Evidence]
) -> Callable[[Run], list[Claim]]:
    """Bind one symbol's evidence without capturing the outer loop variable."""

    def draft(run: Run) -> list[Claim]:
        return claim_factory(run, evidence)

    return draft


def run_comparison(
    symbols: Sequence[str],
    evidence_by_symbol: dict[str, list[Evidence]],
    claim_factory: ClaimFactory,
) -> list[ReviewMetrics]:
    """Run identical tickers with and without the review loop.

    The same claim factory and evidence pool are used for both conditions. The
    only experimental variable is whether the evaluator loop is part of the
    production path; the baseline is then scored with the same evaluator as a
    measurement instrument.
    """
    results: list[ReviewMetrics] = []
    for symbol in symbols:
        evidence = evidence_by_symbol.get(symbol, [])
        results.extend(
            compare_conditions(symbol, evidence, _bind_evidence(claim_factory, evidence))
        )
    return results


def rows_for_notebook(metrics: Sequence[ReviewMetrics]) -> list[MetricsRow]:
    """Return tidy rows ready for ``pd.DataFrame(rows_for_notebook(...))``."""
    return metrics_to_rows(metrics)


def plot_support_comparison(metrics: Sequence[ReviewMetrics]) -> tuple[Figure, Axes]:
    """Create a support-count chart for the final notebook.

    Matplotlib is imported lazily so the core evaluation package remains
    usable in headless or minimal test environments. The function returns the
    figure and axes so the notebook can display or save them.
    """
    import matplotlib.pyplot as plt

    rows = rows_for_notebook(metrics)
    labels = [f"{row['symbol']}\n{row['condition']}" for row in rows]
    supported = [row["supported"] for row in rows]
    unsupported = [row["unsupported"] for row in rows]

    figure, axis = plt.subplots(figsize=(10, 5))
    positions = list(range(len(rows)))
    width = 0.38
    axis.bar([p - width / 2 for p in positions], supported, width, label="Supported")
    axis.bar([p + width / 2 for p in positions], unsupported, width, label="Unsupported")
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
