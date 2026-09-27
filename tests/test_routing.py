"""Tests for routing planner tasks to source-specific gatherers."""

import pytest

from investment_committee.agents.planner import build_plan
from investment_committee.models import Evidence, Run
from investment_committee.workflows.chaining import RawArticle
from investment_committee.workflows.routing import route_plan


def _evidence(run, source):
    return Evidence(
        run_id=run.run_id,
        symbol=run.symbol,
        source=source,
        title=f"{source} fact",
        content="Saved test fact.",
        as_of="2026-09-25",
        reference=f"fixture:{source}",
    )


def test_router_calls_each_handler_in_plan_order():
    run = Run(run_id="r1", symbol="AAPL")
    plan = build_plan("AAPL")
    calls = []

    def earnings(current_run):
        calls.append("earnings")
        return [_evidence(current_run, "earnings")]

    def news(current_run):
        calls.append("news")
        return [
            RawArticle(
                article_id="n1",
                symbol=current_run.symbol,
                source="fixture",
                published="2026-09-25",
                title="Saved article",
                body="Saved article body.",
            )
        ]

    def market(current_run):
        calls.append("market")
        return [_evidence(current_run, "market")]

    results = route_plan(
        run,
        plan,
        gatherers={"earnings": earnings, "news": news, "market": market},
    )

    assert calls == ["earnings", "news", "market"]
    assert list(results) == calls
    assert results["news"][0].symbol == "AAPL"


def test_router_requires_a_handler_for_every_planned_source():
    run = Run(symbol="AAPL")
    with pytest.raises(KeyError, match="news"):
        route_plan(run, build_plan("AAPL"), gatherers={"earnings": lambda _: []})


def test_router_rejects_a_plan_for_another_symbol():
    with pytest.raises(ValueError, match="different stock symbols"):
        route_plan(Run(symbol="TSLA"), build_plan("AAPL"), gatherers={})


def test_router_passes_a_normalized_run_to_gatherers():
    symbols = []

    def gatherer(run):
        symbols.append(run.symbol)
        return []

    gatherers = {"earnings": gatherer, "news": gatherer, "market": gatherer}
    route_plan(Run(symbol=" aapl "), build_plan("AAPL"), gatherers=gatherers)

    assert symbols == ["AAPL", "AAPL", "AAPL"]
