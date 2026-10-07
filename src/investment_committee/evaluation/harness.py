"""Small evaluation harness for the final notebook.

The harness keeps orchestration separate from plotting. It can run the same
symbols through the same claim generator with the evaluator loop disabled and
enabled, then return a tidy list suitable for pandas and matplotlib.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from investment_committee.evaluation.metrics import (
    ReviewMetrics,
    compare_conditions,
    metrics_to_rows,
)
from investment_committee.models import Claim, Evidence, Run

ClaimFactory = Callable[[Run, list[Evidence]], list[Claim]]


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
            compare_conditions(symbol, evidence, lambda run: claim_factory(run, evidence))
        )
    return results


def rows_for_notebook(metrics: Sequence[ReviewMetrics]) -> list[dict[str, object]]:
    """Return tidy rows ready for ``pd.DataFrame(rows_for_notebook(...))``."""
    return metrics_to_rows(metrics)


def plot_support_comparison(metrics: Sequence[ReviewMetrics]):
    """Create a support-count chart for the final notebook.

    Matplotlib is imported lazily so the core evaluation package remains
    usable in headless or minimal test environments. The function returns the
    figure and axes so the notebook can display or save them.
    """
    import matplotlib.pyplot as plt

    rows = rows_for_notebook(metrics)
    labels = [
        f"{row['symbol']}\n{row['condition']}"
        for row in rows
    ]
    supported = [int(row["supported"]) for row in rows]
    unsupported = [int(row["unsupported"]) for row in rows]

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
