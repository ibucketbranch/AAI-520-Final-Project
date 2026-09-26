"""Small Streamlit interface for the current research runner."""

from __future__ import annotations

import streamlit as st

from investment_committee.models import Evidence
from investment_committee.workflows.chaining import RawArticle
from investment_committee.workflows.runner import ResearchSnapshot, run_research


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
    if snapshot.database_path is not None:
        st.success(
            f"Saved run {snapshot.run.run_id} and {snapshot.saved_evidence_count} evidence "
            f"records to {snapshot.database_path}."
        )

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
        "Raw news stays in this snapshot until the news chain converts it to evidence. "
        "Bull/Bear analysis, review, and the final memo are not connected yet."
    )


st.set_page_config(page_title="AI Investment Committee", page_icon=None, layout="wide")
st.title("AI Investment Committee")
st.caption("Planner and live research gatherers")

with st.form("research-form"):
    ticker = st.text_input("Stock symbol", value="AAPL", max_chars=10)
    submitted = st.form_submit_button("Run research", type="primary")

if submitted:
    try:
        with st.spinner(f"Gathering research for {ticker.strip().upper()}..."):
            current_snapshot = run_research(ticker)
    except Exception as error:  # Streamlit should report provider and validation failures cleanly.
        st.error(str(error))
    else:
        show_results(current_snapshot)
