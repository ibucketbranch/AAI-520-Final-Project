"""Evaluation metrics for the investment committee.

The lightweight metrics score the same evidence and claim generator under both
conditions. The storage-backed metrics read complete committee runs from
SQLite for the final notebook's results table.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict

from investment_committee.agents.evaluator import evaluate_claims
from investment_committee.models import Claim, Evidence, Run
from investment_committee.storage import load_claims, load_model_calls, load_run

_MEMO_PREFIX = "Verdict: "
_ROUNDS_PATTERN = re.compile(r" after (?P<rounds>\d+) round\(s\);")


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


@dataclass(frozen=True)
class RunScore:
    """One deliberation's numbers, read back from its stored rows.

    claims_rejected counts claims the evaluator judged unsupported at any
    point, so on a with-review run it includes drafts that were later
    replaced; it is telemetry about the loop, not the final slate.
    """

    run_id: str
    symbol: str
    with_review: bool
    verdict: str
    rounds: int
    claims_supported: int
    claims_rejected: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int


def score_run(conn: sqlite3.Connection, run_id: str) -> RunScore:
    """Score one finished committee run from storage.

    Args:
        conn: An open connection from open_db().
        run_id: A committee run that finished and wrote its memo.

    Returns:
        The run's scorecard.

    Raises:
        ValueError: If the run is missing, never finished, or its memo does
            not carry the committee's verdict line.
    """
    run = load_run(conn, run_id)
    if run is None:
        raise ValueError(f"run {run_id!r} is not in this database")
    if run.memo is None:
        raise ValueError(f"run {run_id!r} never finished; there is no memo to score")
    claims = load_claims(conn, run_id)
    calls = load_model_calls(conn, run_id)
    return RunScore(
        run_id=run_id,
        symbol=run.symbol,
        with_review=run.with_review,
        verdict=_verdict_from_memo(run_id, run.memo),
        rounds=_rounds_from_memo(run_id, run.memo),
        claims_supported=sum(1 for claim in claims if claim.supported),
        claims_rejected=sum(1 for claim in claims if claim.supported is False),
        model_calls=len(calls),
        prompt_tokens=sum(call.prompt_tokens for call in calls),
        completion_tokens=sum(call.completion_tokens for call in calls),
    )


def comparison_rows(conn: sqlite3.Connection, run_ids: Sequence[str]) -> list[dict[str, object]]:
    """Build the comparison table, one row per run, ready for a DataFrame.

    Args:
        conn: An open connection from open_db().
        run_ids: The finished runs to compare, in display order.

    Returns:
        Plain dict rows so the notebook can pandas.DataFrame() them.
    """
    rows: list[dict[str, object]] = []
    for run_id in run_ids:
        score = score_run(conn, run_id)
        rows.append(
            {
                "symbol": score.symbol,
                "review loop": "on" if score.with_review else "off",
                "verdict": score.verdict,
                "rounds": score.rounds,
                "supported claims": score.claims_supported,
                "rejected drafts": score.claims_rejected,
                "model calls": score.model_calls,
                "tokens": score.prompt_tokens + score.completion_tokens,
                "run id": score.run_id,
            }
        )
    return rows


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


def _verdict_from_memo(run_id: str, memo: str) -> str:
    """Pull the verdict side out of the memo's first line."""
    first_line = memo.splitlines()[0]
    if not first_line.startswith(_MEMO_PREFIX):
        raise ValueError(
            f"run {run_id!r} has a memo that does not start with {_MEMO_PREFIX!r}; "
            "it was not written by the committee"
        )
    return first_line[len(_MEMO_PREFIX) :].split(".", 1)[0]


def _rounds_from_memo(run_id: str, memo: str) -> int:
    """Read the workflow's actual round count from its diagnostics line."""
    match = _ROUNDS_PATTERN.search(memo)
    if match is None:
        raise ValueError(f"run {run_id!r} has a memo without the committee's round diagnostics")
    return int(match.group("rounds"))
