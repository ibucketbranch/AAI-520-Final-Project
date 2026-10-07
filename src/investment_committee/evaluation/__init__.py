"""Evaluation utilities for the investment committee.

The package measures claim support under the same inputs with and without the
review loop. Plotting is intentionally left to the final notebook so the
library stays lightweight and testable.
"""

from investment_committee.evaluation.harness import (
    plot_support_comparison,
    rows_for_notebook,
    run_comparison,
)
from investment_committee.evaluation.metrics import ReviewMetrics, score_claims

__all__ = [
    "ReviewMetrics",
    "plot_support_comparison",
    "run_comparison",
    "rows_for_notebook",
    "score_claims",
]
