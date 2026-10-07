"""Tests for the with/without-review evaluation harness."""

from investment_committee.evaluation.harness import (
    plot_support_comparison,
    run_comparison,
    rows_for_notebook,
)
from investment_committee.models import Claim, Evidence, Run


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
