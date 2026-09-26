"""Tests for the planner-and-gatherer runner."""

import pytest

from investment_committee.models import Evidence
from investment_committee.workflows.chaining import RawArticle
from investment_committee.workflows.runner import run_research


def _evidence(run, source):
    return Evidence(
        run_id=run.run_id,
        symbol=run.symbol,
        source=source,
        title=f"{source} fact",
        content="Saved test fact.",
        as_of="2026-09-26",
        reference=f"fixture:{source}",
    )


def test_run_research_normalizes_symbol_and_calls_each_gatherer():
    def news(run):
        return [
            RawArticle(
                article_id="n1",
                symbol=run.symbol,
                source="fixture",
                published="2026-09-26",
                title="Saved headline",
                body="Saved article body.",
            )
        ]

    snapshot = run_research(
        " aapl ",
        gatherers={
            "earnings": lambda run: [_evidence(run, "earnings")],
            "news": news,
            "market": lambda run: [_evidence(run, "market")],
        },
    )

    assert snapshot.run.symbol == "AAPL"
    assert snapshot.plan.symbol == "AAPL"
    assert list(snapshot.gathered) == ["earnings", "news", "market"]
    assert snapshot.gathered["news"][0].symbol == "AAPL"


def test_run_research_rejects_an_invalid_symbol_before_gathering():
    with pytest.raises(ValueError, match="Invalid stock symbol"):
        run_research("not a ticker", gatherers={})
