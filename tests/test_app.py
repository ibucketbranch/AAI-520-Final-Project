"""Check model selection in Streamlit without calling any external service."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from investment_committee.agents.planner import PlannerProviderError
from investment_committee.config import Settings
from investment_committee.workflows.runner import run_research

APP = Path(__file__).parents[1] / "app.py"


@pytest.fixture()
def ui_services(monkeypatch):
    st.cache_data.clear()
    catalog = Mock(return_value=["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"])
    snapshot = run_research(
        "AAPL",
        gatherers={"earnings": lambda run: [], "news": lambda run: [], "market": lambda run: []},
        database_path=None,
        planner_provider="rules",
    )
    runner = Mock(return_value=snapshot)
    monkeypatch.setattr("investment_committee.agents.planner.list_planner_models", catalog)
    monkeypatch.setattr("investment_committee.workflows.runner.run_research", runner)
    monkeypatch.setattr("investment_committee.config.load_settings", lambda: Settings(values={}))
    yield catalog, runner
    st.cache_data.clear()


def test_ui_loads_models_and_passes_the_selection_only_when_run_is_clicked(ui_services):
    catalog, runner = ui_services
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.selectbox(key="openai_model").value == "gpt-6-luna"
    app.selectbox(key="openai_model").select("gpt-6-sol").run()
    runner.assert_not_called()
    catalog.assert_called_once_with("openai")

    app.button(key="run_research").click().run()
    assert not app.exception
    assert not app.error
    runner.assert_called_once_with("AAPL", planner_provider="openai", planner_model="gpt-6-sol")
    assert len(app.subheader) == 1

    app.selectbox(key="openai_model").select("gpt-6-luna").run()
    assert len(app.subheader) == 1
    assert runner.call_count == 1


def test_switching_to_rules_hides_models_and_skips_discovery(ui_services):
    catalog, runner = ui_services
    app = AppTest.from_file(str(APP)).run()
    app.selectbox(key="planner_provider").select("Rule-based").run()
    assert len(app.selectbox) == 1
    assert catalog.call_count == 1
    app.button(key="run_research").click().run()
    assert not app.exception
    runner.assert_called_once_with("AAPL", planner_provider="rules", planner_model=None)

    app.selectbox(key="planner_provider").select("OpenAI").run()
    assert app.selectbox(key="openai_model").value == "gpt-6-luna"


def test_catalog_failure_keeps_old_defaults_hidden_and_refresh_recovers(ui_services, monkeypatch):
    catalog, runner = ui_services
    monkeypatch.setattr(
        "investment_committee.config.load_settings",
        lambda: Settings(values={"OPENAI_MODEL": "gpt-4.1-mini"}),
    )
    catalog.side_effect = PlannerProviderError("Could not load OpenAI models.")
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert "default model" in app.warning[0].value
    assert app.selectbox(key="openai_model").options == ["gpt-6-luna"]
    runner.assert_not_called()

    catalog.side_effect = None
    app.button(key="refresh_models").click().run()
    assert not app.exception
    assert not app.warning
    assert app.selectbox(key="openai_model").options == ["gpt-6-luna", "gpt-6-sol", "gpt-6-astra"]


def test_unavailable_default_is_not_added_to_the_provider_list(ui_services):
    catalog, runner = ui_services
    catalog.return_value = ["gpt-6-sol"]
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.selectbox(key="openai_model").options == ["gpt-6-sol"]
    assert app.selectbox(key="openai_model").value == "gpt-6-sol"
    runner.assert_not_called()


def test_memory_warning_does_not_hide_a_successful_save(ui_services):
    _, runner = ui_services
    runner.return_value = replace(
        runner.return_value,
        memory_error="database unavailable",
        database_path="data/committee.db",
        saved_evidence_count=2,
    )
    app = AppTest.from_file(str(APP)).run()
    app.button(key="run_research").click().run()
    assert not app.exception
    warnings = [item.value for item in app.warning]
    assert "Planned without previous memory: database unavailable" in warnings
    assert "News: News articles were not processed into evidence." in warnings
    assert "2 evidence records" in app.success[0].value
