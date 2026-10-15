"""Small Streamlit interface for the current research runner."""

from __future__ import annotations

import streamlit as st

from investment_committee.agents.planner import (
    CURRENT_OPENAI_MODELS,
    DEFAULT_OPENAI_MODEL,
    PlannerProvider,
    PlannerProviderError,
    list_planner_models,
)
from investment_committee.config import MissingKeyError, load_settings
from investment_committee.models import Evidence
from investment_committee.workflows.chaining import RawArticle
from investment_committee.workflows.runner import ResearchSnapshot, run_research
from ui_committee import live_view, replay_view


@st.cache_data(ttl=300, show_spinner=False)
def available_models(provider: PlannerProvider) -> list[str]:
    """Reuse the model list for five minutes between page updates."""
    return list_planner_models(provider)


def evidence_rows(items: list[Evidence]) -> list[dict[str, str]]:
    """Convert evidence records to rows Streamlit can display."""
    return [
        {
            "Finding": item.title,
            "Details": item.content,
            "As of": item.as_of,
            "Reference": item.reference,
        }
        for item in items
    ]


def article_rows(items: list[RawArticle]) -> list[dict[str, str]]:
    """Convert news articles to rows Streamlit can display."""
    return [
        {
            "Headline": item.title,
            "Source": item.source,
            "Published": item.published,
            "Summary": item.body,
        }
        for item in items
    ]


def show_results(snapshot: ResearchSnapshot) -> None:
    """Render a completed research snapshot."""
    st.subheader(f"Research snapshot: {snapshot.run.symbol}")
    if snapshot.planner_fallback_reason is not None:
        st.warning(
            "The OpenAI planner was not available, so the rule-based planner was used. "
            f"{snapshot.planner_fallback_reason}"
        )
    elif snapshot.planner_model is not None:
        st.caption(f"Planner: OpenAI ({snapshot.planner_model})")
    else:
        st.caption("Planner: Rule-based")

    if snapshot.memory_error is not None:
        st.warning(f"Planned without previous memory: {snapshot.memory_error}")

    if snapshot.storage_error is not None:
        st.warning(f"Research completed, but SQLite could not save it: {snapshot.storage_error}")
    elif snapshot.database_path is not None:
        st.success(
            f"Saved run {snapshot.run.run_id} and {snapshot.saved_evidence_count} evidence "
            f"records to {snapshot.database_path}."
        )

    for source, message in snapshot.gather_errors.items():
        st.warning(f"{source.title()}: {message}")

    plan_rows = [
        {"Step": number, "Source": task.source.title(), "Reason": task.reason}
        for number, task in enumerate(snapshot.plan.tasks, start=1)
    ]
    st.markdown("#### Planner")
    st.dataframe(plan_rows, hide_index=True, width="stretch")

    counts = {source: len(items) for source, items in snapshot.gathered.items()}
    columns = st.columns(3)
    for column, source in zip(columns, ("earnings", "news", "market"), strict=True):
        column.metric(source.title(), counts.get(source, 0))

    earnings_tab, news_tab, market_tab = st.tabs(["Earnings", "News", "Market"])
    with earnings_tab:
        earnings = snapshot.gathered.get("earnings", [])
        st.dataframe(evidence_rows(earnings), hide_index=True, width="stretch")
    with news_tab:
        news = snapshot.gathered.get("news", [])
        st.dataframe(article_rows(news), hide_index=True, width="stretch")
    with market_tab:
        market = snapshot.gathered.get("market", [])
        st.dataframe(evidence_rows(market), hide_index=True, width="stretch")

    st.info(
        "News is processed by the classification gate before gate-approved articles are "
        "promoted into the shared Evidence pool. Bull/Bear analysis and the final review "
        "memo are still separate workflow stages."
    )


st.set_page_config(page_title="AI Investment Committee", page_icon=None, layout="wide")
st.title("AI Investment Committee")

# The committee views live in ui_committee.py. Research stays the first view,
# and st.stop() ends the run so the research form below is not drawn under them.
view = st.sidebar.radio("View", ["Research", "Committee replay", "Live committee"], key="view")
if view == "Committee replay":
    replay_view()
    st.stop()
if view == "Live committee":
    live_view()
    st.stop()

st.caption("Planner and live research gatherers")

with st.container(border=True):
    ticker = st.text_input("Stock symbol", value="AAPL", max_chars=10)
    planner_name = st.selectbox(
        "Planner provider", ["OpenAI", "Rule-based"], index=0, key="planner_provider"
    )
    planner_provider: PlannerProvider = "openai" if planner_name == "OpenAI" else "rules"
    planner_model = None

    if planner_provider == "openai":
        default_model = load_settings().values.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        if default_model not in CURRENT_OPENAI_MODELS:
            default_model = DEFAULT_OPENAI_MODEL
        model_column, refresh_column = st.columns([8, 1], vertical_alignment="bottom")
        with refresh_column:
            if st.button(
                "", icon=":material/refresh:", help="Refresh models", key="refresh_models"
            ):
                available_models.clear()

        with model_column:
            try:
                with st.spinner("Loading models..."):
                    models = available_models(planner_provider)
            except (MissingKeyError, PlannerProviderError) as error:
                st.warning(f"{error} Showing the default model: {default_model}.")
                models = [default_model]

            if st.session_state.get("openai_model") not in models:
                st.session_state["openai_model"] = (
                    default_model if default_model in models else models[0]
                )
            planner_model = st.selectbox("Model", models, key="openai_model")

    submitted = st.button("Run research", type="primary", key="run_research")

if submitted:
    try:
        with st.spinner(f"Gathering research for {ticker.strip().upper()}..."):
            current_snapshot = run_research(
                ticker, planner_provider=planner_provider, planner_model=planner_model
            )
    except Exception as error:  # Streamlit should report provider and validation failures cleanly.
        st.session_state.pop("research_snapshot", None)
        st.error(str(error))
    else:
        st.session_state["research_snapshot"] = current_snapshot

if "research_snapshot" in st.session_state:
    show_results(st.session_state["research_snapshot"])
