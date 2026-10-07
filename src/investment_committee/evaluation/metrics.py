"""Evaluation metrics for the investment committee.

The metrics use the same evidence and claim generator for both conditions.
The no-review draft is post-hoc scored only as a measurement instrument; it is
not modified. The reviewed condition is actually passed through the evaluator.
This keeps the comparison fair while preserving the distinction between the
production path and the baseline path.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict

from investment_committee.agents.evaluator import evaluate_claims
from investment_committee.models import Claim, Evidence, Run


@dataclass(frozen=True)
class ReviewMetrics:
    """Counts used for one evaluation condition."""

    symbol: str
    with_review: bool
    total_claims: int
    supported: int
    unsupported: int
    unresolved: int

    @property
    def support_rate(self) -> float:
        """Return supported / resolved claims, or 0 when nothing is resolved."""
        resolved = self.supported + self.unsupported
        return self.supported / resolved if resolved else 0.0


class MetricsRow(TypedDict):
    """One typed row for the notebook comparison table."""

    symbol: str
    condition: str
    total_claims: int
    supported: int
    unsupported: int
    unresolved: int
    support_rate: float


def score_claims(claims: Sequence[Claim]) -> tuple[int, int, int]:
    """Count supported, unsupported, and unresolved claim verdicts."""
    supported = sum(claim.supported is True for claim in claims)
    unsupported = sum(claim.supported is False for claim in claims)
    unresolved = sum(claim.supported is None for claim in claims)
    return supported, unsupported, unresolved


def evaluate_condition(
    symbol: str,
    claims: list[Claim],
    evidence: list[Evidence],
    *,
    with_review: bool,
) -> tuple[list[Claim], ReviewMetrics]:
    """Run one condition and return its claims plus support metrics."""
    final_claims = evaluate_claims(claims, evidence)
    supported, unsupported, unresolved = score_claims(final_claims)
    return final_claims, ReviewMetrics(
        symbol=symbol,
        with_review=with_review,
        total_claims=len(final_claims),
        supported=supported,
        unsupported=unsupported,
        unresolved=unresolved,
    )


def compare_conditions(
    symbol: str,
    evidence: list[Evidence],
    draft_claims: Callable[[Run], list[Claim]],
) -> list[ReviewMetrics]:
    """Run the same ticker with and without the review loop.

    The baseline claims are generated without a review pass and then scored
    separately so the notebook can count supported vs unsupported statements.
    The reviewed claims go through the same evaluator as the production path.
    """
    results: list[ReviewMetrics] = []

    baseline_run = Run(symbol=symbol, with_review=False)
    baseline_claims = draft_claims(baseline_run)
    _, baseline_metrics = evaluate_condition(symbol, baseline_claims, evidence, with_review=False)
    results.append(baseline_metrics)

    reviewed_run = Run(symbol=symbol, with_review=True)
    reviewed_claims = draft_claims(reviewed_run)
    _, reviewed_metrics = evaluate_condition(symbol, reviewed_claims, evidence, with_review=True)
    results.append(reviewed_metrics)
    return results


def metrics_to_rows(metrics: Sequence[ReviewMetrics]) -> list[MetricsRow]:
    """Convert metrics to notebook-friendly rows for pandas/DataFrame use."""
    return [
        {
            "symbol": item.symbol,
            "condition": "with review" if item.with_review else "without review",
            "total_claims": item.total_claims,
            "supported": item.supported,
            "unsupported": item.unsupported,
            "unresolved": item.unresolved,
            "support_rate": item.support_rate,
        }
        for item in metrics
    ]
