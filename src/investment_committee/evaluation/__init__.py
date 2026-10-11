"""Evaluation utilities for the investment committee.

The package measures claim support under the same inputs with and without the
review loop. Plotting is intentionally left to the final notebook so the
library stays lightweight and testable. The storage-backed APIs also run and
score complete committee deliberations persisted in SQLite.
"""

from investment_committee.evaluation.harness import (
    ReviewComparison,
    plot_support_comparison,
    rows_for_notebook,
    run_comparison,
    run_review_comparison,
)
from investment_committee.evaluation.metrics import (
    ReviewMetrics,
    RunScore,
    comparison_rows,
    score_claims,
    score_run,
)

__all__ = [
    "ReviewComparison",
    "ReviewMetrics",
    "RunScore",
    "comparison_rows",
    "plot_support_comparison",
    "rows_for_notebook",
    "run_comparison",
    "run_review_comparison",
    "score_claims",
    "score_run",
]
