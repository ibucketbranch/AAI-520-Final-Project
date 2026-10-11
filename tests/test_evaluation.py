"""Tests for the A/B harness and the metrics, no network calls."""

import pytest
from test_committee import RoutingFakeClient, make_run, one_claim, pool, settings_with

from investment_committee.agents.evaluator import ClaimVerdict
from investment_committee.evaluation.harness import run_review_comparison
from investment_committee.evaluation.metrics import comparison_rows, score_run
from investment_committee.models import Run
from investment_committee.storage import load_run, open_db, save_run, save_run_with_evidence
from investment_committee.workflows.evaluator_optimizer import CommitteeVerdict


def seeded_conn():
    conn = open_db(":memory:")
    parent = make_run()
    save_run_with_evidence(conn, parent, pool(parent.run_id))
    return conn, parent


def both_arms_client():
    """Queues for two arms where every claim passes on the first judgment."""
    return RoutingFakeClient(
        drafts=[
            one_claim("ev-1", text="Bull argument"),
            one_claim("ev-2", text="Bear argument"),
            one_claim("ev-1", text="Bull argument"),
            one_claim("ev-2", text="Bear argument"),
        ],
        verdicts=[ClaimVerdict(supported=True, reason="matches the source")] * 4,
        decisions=[
            CommitteeVerdict(side="none", reason="balanced after review"),
            CommitteeVerdict(side="bull", reason="the upside case reads stronger"),
        ],
    )


def test_review_comparison_runs_both_arms_off_one_parent():
    """Damage prevented: the two arms drifting onto different evidence pools."""
    conn, parent = seeded_conn()
    comparison = run_review_comparison(
        conn, parent.run_id, settings_with(OPENAI_API_KEY="k"), client=both_arms_client()
    )
    assert comparison.with_review.run.with_review is True
    assert comparison.without_review.run.with_review is False
    assert comparison.with_review.run.parent_run_id == parent.run_id
    assert comparison.without_review.run.parent_run_id == parent.run_id
    assert comparison.with_review.verdict == "none"
    assert comparison.without_review.verdict == "bull"
    for result in (comparison.with_review, comparison.without_review):
        stored = load_run(conn, result.run.run_id)
        assert stored is not None and stored.memo is not None


def test_review_comparison_fails_loudly_without_the_parent():
    """Damage prevented: silently deliberating an empty pool."""
    conn = open_db(":memory:")
    with pytest.raises(ValueError, match="gather or seed"):
        run_review_comparison(conn, "no-such-run", settings_with(OPENAI_API_KEY="k"))


def test_score_run_reads_the_numbers_back_from_storage():
    """Damage prevented: the notebook table disagreeing with the stored run."""
    conn, parent = seeded_conn()
    comparison = run_review_comparison(
        conn, parent.run_id, settings_with(OPENAI_API_KEY="k"), client=both_arms_client()
    )
    score = score_run(conn, comparison.without_review.run.run_id)
    assert score.verdict == "bull"
    assert score.with_review is False
    assert score.rounds == 1
    assert score.claims_supported == 2
    assert score.claims_rejected == 0
    # bull draft + bear draft + two judgments + the verdict
    assert score.model_calls == 5
    assert score.prompt_tokens == 50
    assert score.completion_tokens == 25


def test_score_run_counts_a_rejected_draft_and_the_extra_round():
    """Damage prevented: the loop's work vanishing from the comparison."""
    conn, parent = seeded_conn()
    client = RoutingFakeClient(
        drafts=[
            one_claim("ev-1", text="Bull argument"),
            one_claim("ev-2", text="Bear argument, weak"),
            one_claim("ev-2", text="Bear argument, grounded"),
        ],
        verdicts=[
            ClaimVerdict(supported=True, reason="matches the source"),
            ClaimVerdict(supported=False, reason="the source does not say that"),
            ClaimVerdict(supported=True, reason="matches the numbers"),
        ],
        decisions=[CommitteeVerdict(side="bear", reason="the risk case held up")],
    )
    run = Run(symbol=parent.symbol, with_review=True, parent_run_id=parent.run_id)
    save_run(conn, run)
    from investment_committee.workflows.evaluator_optimizer import run_committee_from_storage

    run_committee_from_storage(conn, run.run_id, settings_with(OPENAI_API_KEY="k"), client=client)
    score = score_run(conn, run.run_id)
    assert score.verdict == "bear"
    assert score.rounds == 2
    assert score.claims_supported == 2
    assert score.claims_rejected == 1


def test_score_run_fails_loudly_on_missing_and_unfinished_runs():
    """Damage prevented: scoring a run that never deliberated."""
    conn, parent = seeded_conn()
    with pytest.raises(ValueError, match="not in this database"):
        score_run(conn, "no-such-run")
    unfinished = Run(symbol=parent.symbol, parent_run_id=parent.run_id)
    save_run(conn, unfinished)
    with pytest.raises(ValueError, match="never finished"):
        score_run(conn, unfinished.run_id)


def test_comparison_rows_build_the_notebook_table():
    """Damage prevented: a table the notebook cannot feed to a DataFrame."""
    conn, parent = seeded_conn()
    comparison = run_review_comparison(
        conn, parent.run_id, settings_with(OPENAI_API_KEY="k"), client=both_arms_client()
    )
    rows = comparison_rows(
        conn, [comparison.with_review.run.run_id, comparison.without_review.run.run_id]
    )
    assert [row["review loop"] for row in rows] == ["on", "off"]
    assert [row["verdict"] for row in rows] == ["none", "bull"]
    assert all(row["symbol"] == parent.symbol for row in rows)
    assert {"rounds", "supported claims", "rejected drafts", "model calls", "tokens"} <= set(
        rows[0]
    )
