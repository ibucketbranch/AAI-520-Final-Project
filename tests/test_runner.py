"""Tests for the planner-and-gatherer runner."""

from contextlib import closing

import pytest

from investment_committee.agents.planner import PlanningResult, build_plan
from investment_committee.models import Evidence, ModelCall
from investment_committee.storage import load_evidence, load_model_calls, load_run, open_db
from investment_committee.tools.earnings import EarningsDataError
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
        database_path=None,
        planner_provider="rules",
    )

    assert snapshot.run.symbol == "AAPL"
    assert snapshot.plan.symbol == "AAPL"
    assert list(snapshot.gathered) == ["earnings", "news", "market"]
    assert snapshot.gathered["news"][0].symbol == "AAPL"


def test_run_research_rejects_an_invalid_symbol_before_gathering():
    with pytest.raises(ValueError, match="Invalid stock symbol"):
        run_research("not a ticker", gatherers={}, database_path=None, planner_provider="rules")


def test_run_research_saves_run_and_evidence_but_not_raw_news(tmp_path):
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

    database_path = tmp_path / "committee.db"
    snapshot = run_research(
        "AAPL",
        gatherers={
            "earnings": lambda run: [_evidence(run, "earnings")],
            "news": news,
            "market": lambda run: [_evidence(run, "market")],
        },
        database_path=database_path,
        planner_provider="rules",
    )

    with closing(open_db(database_path)) as conn:
        stored_run = load_run(conn, snapshot.run.run_id)
        stored_evidence = load_evidence(conn, snapshot.run.run_id)

    assert stored_run == snapshot.run
    assert [item.source for item in stored_evidence] == ["earnings", "market"]
    assert snapshot.saved_evidence_count == 2
    assert snapshot.database_path == str(database_path)
    assert snapshot.storage_error is None


def test_run_research_returns_gathered_results_when_atomic_save_fails(tmp_path):
    def wrong_run_evidence(run):
        item = _evidence(run, "earnings")
        return [item.model_copy(update={"run_id": "another-run"})]

    database_path = tmp_path / "committee.db"
    snapshot = run_research(
        "AAPL",
        gatherers={
            "earnings": wrong_run_evidence,
            "news": lambda run: [],
            "market": lambda run: [],
        },
        database_path=database_path,
        planner_provider="rules",
    )

    with closing(open_db(database_path)) as conn:
        stored_run = load_run(conn, snapshot.run.run_id)

    assert len(snapshot.gathered["earnings"]) == 1
    assert stored_run is None
    assert snapshot.saved_evidence_count == 0
    assert snapshot.database_path is None
    assert snapshot.storage_error is not None


def test_run_research_keeps_other_sources_when_one_has_no_data():
    def no_earnings(run):
        raise EarningsDataError(f"No quarterly income statement returned for {run.symbol}.")

    snapshot = run_research(
        "DRAM",
        gatherers={
            "earnings": no_earnings,
            "news": lambda run: [],
            "market": lambda run: [_evidence(run, "market")],
        },
        database_path=None,
        planner_provider="rules",
    )

    assert snapshot.gathered["earnings"] == []
    assert len(snapshot.gathered["market"]) == 1
    assert snapshot.gather_errors == {
        "earnings": "No quarterly income statement returned for DRAM."
    }


def test_run_research_still_raises_unexpected_gatherer_errors():
    def broken(run):
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        run_research(
            "AAPL",
            gatherers={"earnings": broken, "news": lambda run: [], "market": lambda run: []},
            database_path=None,
            planner_provider="rules",
        )


def test_run_research_reports_the_selected_rule_based_planner():
    snapshot = run_research(
        "AAPL",
        gatherers={"earnings": lambda run: [], "news": lambda run: [], "market": lambda run: []},
        database_path=None,
        planner_provider="rules",
    )

    assert snapshot.planner_provider_requested == "rules"
    assert snapshot.planner_provider_used == "rules"
    assert snapshot.planner_fallback_reason is None
    assert snapshot.planner_model is None


def test_runner_passes_the_model_choice_and_saves_the_reported_model(monkeypatch, tmp_path):
    def fake_planner(symbol, run_id, provider, model):
        assert provider == "openai"
        assert model == "gpt-4.1-mini"
        return PlanningResult(
            plan=build_plan(symbol),
            provider_requested=provider,
            provider_used=provider,
            model_call=ModelCall(
                run_id=run_id,
                stage="planner",
                model="gpt-4.1-mini-2025-04-14",
                prompt="Plan research",
                response="Research all three sources",
            ),
        )

    monkeypatch.setattr("investment_committee.workflows.runner.plan_research", fake_planner)
    path = tmp_path / "committee.db"
    snapshot = run_research(
        "AAPL",
        gatherers={"earnings": lambda run: [], "news": lambda run: [], "market": lambda run: []},
        database_path=path,
        planner_provider="openai",
        planner_model="gpt-4.1-mini",
    )
    with closing(open_db(path)) as conn:
        calls = load_model_calls(conn, snapshot.run.run_id)
    assert snapshot.planner_model == "gpt-4.1-mini-2025-04-14"
    assert len(calls) == 1
    assert calls[0].model == snapshot.planner_model
