"""Tests for the metrics seams the evaluation harness and notebook share."""

import pytest

from investment_committee.evaluation.metrics import (
    comparison_rows,
    run_metrics,
    supported_share,
)
from investment_committee.models import Claim, Evidence, Run
from investment_committee.storage import open_db, save_claim, save_run_with_evidence


def claim(run_id, side, supported):
    return Claim(
        run_id=run_id,
        side=side,
        text=f"{side} claim",
        evidence_ids=["ev-1"],
        supported=supported,
    )


def seeded_run(conn, symbol, with_review, supported_flags):
    run = Run(symbol=symbol, with_review=with_review)
    evidence = [
        Evidence(
            run_id=run.run_id,
            symbol=symbol,
            source="news",
            title="Headline",
            content="Body.",
            as_of="2026-09-30",
            reference="fixture",
        )
    ]
    save_run_with_evidence(conn, run, evidence)
    for flag in supported_flags:
        save_claim(conn, claim(run.run_id, "bull", flag))
    return run


def test_supported_share_handles_empty_and_unset():
    assert supported_share([]) == 0.0
    claims = [claim("r", "bull", True), claim("r", "bear", False), claim("r", "bull", None)]
    assert supported_share(claims) == pytest.approx(1 / 3)


def test_run_metrics_counts_stored_claims(tmp_path):
    with open_db(tmp_path / "m.db") as conn:
        run = seeded_run(conn, "NFLX", True, [True, True, False])
        metrics = run_metrics(conn, run.run_id)
    assert metrics.symbol == "NFLX"
    assert metrics.with_review is True
    assert metrics.claims == 3
    assert metrics.supported == 2
    assert metrics.unsupported == 1
    assert metrics.supported_share == pytest.approx(2 / 3)


def test_run_metrics_rejects_unknown_run(tmp_path):
    with open_db(tmp_path / "m.db") as conn:
        with pytest.raises(ValueError):
            run_metrics(conn, "missing")


def test_comparison_rows_keeps_order_and_arms(tmp_path):
    with open_db(tmp_path / "m.db") as conn:
        with_run = seeded_run(conn, "NFLX", True, [True, True])
        without_run = seeded_run(conn, "NFLX", False, [True, False])
        rows = comparison_rows(conn, [with_run.run_id, without_run.run_id])
    assert [row.with_review for row in rows] == [True, False]
    assert rows[0].supported_share == 1.0
    assert rows[1].supported_share == 0.5
