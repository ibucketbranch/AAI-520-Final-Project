"""Metrics for the final notebook's results table.

Reads finished runs back from storage and reports verdicts, rounds, supported
claims, rejected drafts, model calls, token use, and any stage that fell back
to a non-model path (so a citation-only run cannot pass as a judged one).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from investment_committee.storage import load_claims, load_fallbacks, load_model_calls, load_run

_MEMO_PREFIX = "Verdict: "


@dataclass(frozen=True)
class RunScore:
    """One deliberation's numbers, read back from its stored rows.

    claims_rejected counts claims the evaluator judged unsupported at any
    point, so on a with-review run it includes drafts that were later
    replaced; it is telemetry about the loop, not the final slate.
    fallbacks names each stage that degraded and why; empty on a clean run.
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
    fallbacks: dict[str, str]


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
        fallbacks=load_fallbacks(conn, run_id),
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
                "degraded stages": ", ".join(score.fallbacks) or "none",
                "run id": score.run_id,
            }
        )
    return rows


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
    """Read the round count from the memo's diagnostics line."""
    for line in memo.splitlines():
        if not line.startswith("Diagnostics:") or " after " not in line:
            continue
        value = line.split(" after ", 1)[1].split(" ", 1)[0]
        if value.isdigit():
            return int(value)
    raise ValueError(f"run {run_id!r} has no round count in its memo")
