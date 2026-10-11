"""Tests for the with/without-review evaluation harness."""

import pytest
from test_committee import RoutingFakeClient, make_run, one_claim, pool, settings_with

from investment_committee.agents.evaluator import ClaimVerdict
from investment_committee.evaluation.harness import (
    plot_support_comparison,
    rows_for_notebook,
    run_comparison,
    run_review_comparison,
)
from investment_committee.evaluation.metrics import comparison_rows, score_run
from investment_committee.models import Claim, Evidence, Run
from investment_committee.storage import (
    finish_run,
    load_run,
    open_db,
    save_claim,
    save_run,
    save_run_with_evidence,
)
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


def test_score_run_uses_completed_rounds_not_highest_claim_revision():
    """A second round can finish without producing a revision-one claim."""
    conn = open_db(":memory:")
    run = Run(symbol="AAPL", with_review=True)
    save_run(conn, run)
    save_claim(
        conn,
        Claim(
            run_id=run.run_id,
            side="bull",
            text="A surviving first-round claim.",
            evidence_ids=["ev-1"],
            supported=True,
            revision=0,
        ),
    )
    finish_run(
        conn,
        run.run_id,
        "Verdict: bull. Evidence held.\n"
        "Diagnostics: 1 supported bull claim(s), 0 supported bear claim(s) "
        "after 2 round(s); counts informed nothing.",
        "2026-10-10T00:00:00+00:00",
    )

    assert score_run(conn, run.run_id).rounds == 2


def _evidence(run: Run) -> list[Evidence]:
    return [
        Evidence(
            run_id=run.run_id,
            symbol=run.symbol,
            source="news",
            title="Revenue update",
            content="Revenue increased 4 percent.",
            as_of="2026-09-20",
            reference="fixture:news",
        )
    ]


def _claims(run: Run, evidence: list[Evidence]) -> list[Claim]:
    return [
        Claim(
            run_id=run.run_id,
            side="bull",
            text="Revenue increased.",
            evidence_ids=[evidence[0].evidence_id],
        ),
        Claim(
            run_id=run.run_id,
            side="bull",
            text="Unsupported claim.",
            evidence_ids=["missing-evidence"],
        ),
    ]


def test_harness_runs_same_symbol_with_and_without_review():
    seed_run = Run(symbol="AAPL")
    evidence = _evidence(seed_run)
    results = run_comparison(
        ["AAPL"],
        {"AAPL": evidence},
        lambda run, items: _claims(run, items),
    )

    assert [item.with_review for item in results] == [False, True]
    assert results[0].supported == 1
    assert results[0].unsupported == 1
    assert results[1].supported == 1
    assert results[1].unsupported == 1


def test_rows_are_ready_for_notebook_tables():
    seed_run = Run(symbol="AAPL")
    results = run_comparison(
        ["AAPL"],
        {"AAPL": _evidence(seed_run)},
        lambda run, items: _claims(run, items),
    )

    rows = rows_for_notebook(results)
    assert rows[0]["condition"] == "without review"
    assert rows[1]["condition"] == "with review"
    assert rows[1]["support_rate"] == 0.5


def test_plot_support_comparison_returns_matplotlib_objects():
    import matplotlib

    matplotlib.use("Agg")
    seed_run = Run(symbol="AAPL")
    results = run_comparison(
        ["AAPL"],
        {"AAPL": _evidence(seed_run)},
        lambda run, items: _claims(run, items),
    )

    figure, axis = plot_support_comparison(results)
    assert figure is not None
    assert axis.get_ylabel() == "Claim count"
    figure.clf()
