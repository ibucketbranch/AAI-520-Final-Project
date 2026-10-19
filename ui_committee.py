"""Committee replay and live committee views for the Streamlit app.

The research view in app.py stops after the planner and the three data
tools. These two views show what happens next: Bull and Bear draft claims,
the evaluator judges each claim against the evidence it cites, rejected
claims go back for a rewrite (review loop on) or are dropped (review loop
off), and the chair reads only the supported claims to pick a verdict.

Replay reads saved runs from a SQLite file in data/ and costs nothing.
Live runs the real pipeline and makes paid model calls, so it needs a key
and a second click.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from openai import OpenAI

from investment_committee.agents.planner import CURRENT_OPENAI_MODELS
from investment_committee.config import Settings, load_settings
from investment_committee.evaluation.harness import (
    ReviewComparison,
    plot_support_comparison,
    run_review_comparison,
)
from investment_committee.evaluation.metrics import RunScore, comparison_rows, score_run
from investment_committee.models import Claim, Evidence, Run
from investment_committee.storage import load_claims, load_evidence, load_run, open_db
from investment_committee.workflows.runner import ResearchSnapshot, run_research

DATA_DIR = Path("data")
VERDICT_COLORS = {"bull": "green", "bear": "red", "none": "gray"}
SOURCES = ("earnings", "news", "market")


@dataclass(frozen=True)
class GatheringRun:
    """A gathering run plus the committee runs that argued from its evidence."""

    run: Run
    with_review: Run | None
    without_review: Run | None

    @property
    def label(self) -> str:
        """Text for the run picker: symbol, local start time, and which setups exist."""
        setups = []
        if self.with_review is not None:
            setups.append("review on")
        if self.without_review is not None:
            setups.append("review off")
        return f"{self.run.symbol} | {local_time(self.run.started_at)} | {' + '.join(setups)}"


# ---- reading saved runs ------------------------------------------------------


def list_databases(folder: Path = DATA_DIR) -> list[Path]:
    """Return the SQLite files in the data folder, newest first."""
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.db"), key=lambda path: path.stat().st_mtime, reverse=True)


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open a saved database without changing it.

    storage.open_db() creates tables and can migrate an old file, which is
    right for a run but wrong for a replay of someone's saved results. The
    storage load_* functions only need a connection that returns rows by
    name, so this read-only one works with them.
    """
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def local_time(iso_text: str) -> str:
    """Show a stored UTC timestamp in this computer's time zone."""
    try:
        return datetime.fromisoformat(iso_text).astimezone().strftime("%b %d %H:%M")
    except ValueError:
        return iso_text


def gathering_runs(conn: sqlite3.Connection) -> list[GatheringRun]:
    """Find the gathering runs that have at least one finished committee run.

    A committee run is a row in runs whose parent_run_id points at the
    gathering run whose evidence it argued from. storage.py has no
    "list runs" function and src/ is frozen until after submission, so the
    run ids come from one small read-only query here; every record is then
    loaded through storage.load_run.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    if "parent_run_id" not in columns:
        return []
    rows = conn.execute(
        "SELECT run_id FROM runs WHERE parent_run_id IS NOT NULL AND memo IS NOT NULL"
        " ORDER BY started_at"
    ).fetchall()
    committee_runs = [run for row in rows if (run := load_run(conn, row["run_id"])) is not None]

    # Latest committee run of each setup wins if a parent was argued more than once.
    by_parent: dict[str, dict[bool, Run]] = {}
    for run in committee_runs:
        if run.parent_run_id is not None and run.memo and run.memo.startswith("Verdict: "):
            by_parent.setdefault(run.parent_run_id, {})[run.with_review] = run

    found = []
    for parent_id, setups in by_parent.items():
        parent = load_run(conn, parent_id)
        if parent is not None:
            found.append(GatheringRun(parent, setups.get(True), setups.get(False)))
    return sorted(found, key=lambda item: item.run.started_at, reverse=True)


def verdict_reason(memo: str) -> str:
    """Return the chair's one-sentence reason from the memo's first line."""
    first_line = memo.splitlines()[0]
    return first_line.split(". ", 1)[1] if ". " in first_line else ""


def claims_by_round(claims: list[Claim]) -> list[list[Claim]]:
    """Group stored claims into review rounds.

    A first draft has revision 0 and is judged in round 1; a rewrite made
    after round 1 has revision 1 and is judged in round 2, and so on.
    """
    if not claims:
        return []
    last = max(claim.revision for claim in claims)
    return [[claim for claim in claims if claim.revision == number] for number in range(last + 1)]


# ---- drawing claims ------------------------------------------------------------


def as_text(value: str) -> str:
    """Escape dollar signs so Streamlit shows "$109.42" as money, not math."""
    return value.replace("$", "\\$")


def cited_titles(claim: Claim, evidence_by_id: dict[str, Evidence]) -> str:
    """Name the evidence a claim cites, by title and source."""
    names = []
    for evidence_id in claim.evidence_ids:
        item = evidence_by_id.get(evidence_id)
        names.append(f"{item.title} ({item.source})" if item else evidence_id)
    return as_text("; ".join(names))


def show_claim_text(claim: Claim, evidence_by_id: dict[str, Evidence]) -> None:
    """Write one claim and the evidence it cites, before it is judged."""
    st.markdown(as_text(claim.text))
    st.caption(f"Cites: {cited_titles(claim, evidence_by_id)}")


def show_judgment(claim: Claim, after_reject: str) -> None:
    """Write the evaluator's badge and reason under a claim."""
    if claim.supported:
        st.badge("Supported", icon=":material/check:", color="green")
    else:
        st.badge("Rejected", icon=":material/close:", color="red")
    if claim.reason:
        st.caption(f"Evaluator: {as_text(claim.reason)}")
    if not claim.supported:
        st.caption(after_reject)


def play_round(
    claims: list[Claim],
    evidence_by_id: dict[str, Evidence],
    after_reject: str,
    pause: float,
    tick: Callable[[], None],
) -> None:
    """Show one round: Bull and Bear claims side by side, judged one at a time."""
    bull_column, bear_column = st.columns(2)
    bull_column.markdown("**Bull**")
    bear_column.markdown("**Bear**")
    for claim in claims:
        column = bull_column if claim.side == "bull" else bear_column
        with column.container(border=True):
            show_claim_text(claim, evidence_by_id)
            judgment = st.empty()
        time.sleep(pause)
        with judgment.container():
            show_judgment(claim, after_reject)
        tick()


def show_verdict(run: Run, claims: list[Claim], evidence_by_id: dict[str, Evidence]) -> None:
    """Show the verdict card: the side, the chair's reason, and what it read."""
    memo = run.memo or "Verdict: none."
    side = memo.splitlines()[0].removeprefix("Verdict: ").split(".", 1)[0]
    read_by_chair = final_supported(claims)
    with st.container(border=True):
        st.markdown(f"### Verdict: :{VERDICT_COLORS.get(side, 'gray')}[{side.upper()}]")
        st.markdown(as_text(verdict_reason(memo)))
        st.caption(
            "The chair reads only the supported claims. Rejected claims never reach the verdict."
        )
        with st.expander(f"What the chair read ({len(read_by_chair)} supported claims)"):
            for claim in read_by_chair:
                st.markdown(f"- **{claim.side.title()}:** {as_text(claim.text)}")
                st.caption(f"Cites: {cited_titles(claim, evidence_by_id)}")


def final_supported(claims: list[Claim]) -> list[Claim]:
    """Return the claims that were supported when the loop stopped.

    Rejected claims are left out on both setups: dropped when the review
    loop is off, replaced by their rewrites when it is on.
    """
    return [claim for claim in claims if claim.supported]


# ---- replay ----------------------------------------------------------------------


def show_evidence_pool(evidence: list[Evidence]) -> None:
    """Show the evidence pool grouped by source."""
    counts = {source: sum(1 for item in evidence if item.source == source) for source in SOURCES}
    for column, source in zip(st.columns(3), SOURCES, strict=True):
        column.metric(source.title(), counts[source])
    for source in SOURCES:
        items = [item for item in evidence if item.source == source]
        if not items:
            continue
        with st.expander(f"{source.title()} evidence ({len(items)})"):
            rows = [
                {"Finding": item.title, "Details": item.content, "As of": item.as_of}
                for item in items
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def play_review_loop(
    run: Run, claims: list[Claim], evidence_by_id: dict[str, Evidence], pause: float
) -> None:
    """Animate the review-on setup round by round, then show its verdict."""
    rounds = claims_by_round(claims)
    total_steps = len(claims) + 1
    progress = st.progress(0, text="Starting the review loop")
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        progress.progress(min(done / total_steps, 1.0), text=f"Step {done} of {total_steps}")

    for number, round_claims in enumerate(rounds, start=1):
        last_round = number == len(rounds)
        title = "first drafts" if number == 1 else "rewrites of the rejected claims"
        with st.status(f"Round {number}: {title}", expanded=True) as status:
            if number > 1:
                kept = [claim for claim in rounds[0] if claim.supported]
                if kept:
                    st.caption(f"Kept from round 1 without changes: {len(kept)} supported claims.")
            after_reject = (
                "Stopped here: the round limit was reached."
                if last_round
                else "Sent back to its analyst with this reason."
            )
            play_round(round_claims, evidence_by_id, after_reject, pause, tick)
            rejected = [claim for claim in round_claims if not claim.supported]
            label = f"Round {number}: {len(round_claims) - len(rejected)} supported, {len(rejected)} rejected"
            status.update(label=label, state="complete", expanded=True)
        if rejected and not last_round:
            bull_back = sum(1 for claim in rejected if claim.side == "bull")
            bear_back = len(rejected) - bull_back
            st.info(f"Sent back for rewrites: Bull {bull_back}, Bear {bear_back}.")
            time.sleep(pause)
    if len(rounds) == 1:
        st.info("Nothing was rejected in round 1, so nothing went back for a rewrite.")

    time.sleep(pause)
    show_verdict(run, claims, evidence_by_id)
    tick()
    progress.progress(1.0, text="Done")


def show_no_review_setup(
    run: Run, claims: list[Claim], evidence_by_id: dict[str, Evidence]
) -> None:
    """Show the review-off setup: one round, rejected claims dropped."""
    st.caption("Same evidence, one round. Rejected claims are dropped, not rewritten.")
    play_round(
        claims, evidence_by_id, "Dropped: the review loop is off.", pause=0.0, tick=lambda: None
    )
    show_verdict(run, claims, evidence_by_id)


def show_comparison(conn: sqlite3.Connection, with_review: Run, without_review: Run) -> None:
    """Show the side-by-side table and chart for the two setups."""
    run_ids = [with_review.run_id, without_review.run_id]
    st.dataframe(pd.DataFrame(comparison_rows(conn, run_ids)), hide_index=True, width="stretch")
    scores: list[RunScore] = [score_run(conn, run_id) for run_id in run_ids]
    figure, _ = plot_support_comparison(scores)
    st.pyplot(figure)
    plt.close(figure)
    st.caption(
        "Rejected drafts counts every claim the evaluator turned down at any point, so on "
        "the review-on setup it includes drafts that were later rewritten."
    )


def show_replay(database: Path, parent: GatheringRun, pause: float) -> None:
    """Replay one gathering run's committee from a saved database."""
    with closing(open_readonly(database)) as conn:
        evidence = load_evidence(conn, parent.run.run_id)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        st.markdown(f"#### Evidence pool: {parent.run.symbol}")
        show_evidence_pool(evidence)

        if parent.with_review is not None:
            st.markdown("#### Review loop on")
            claims = load_claims(conn, parent.with_review.run_id)
            play_review_loop(parent.with_review, claims, evidence_by_id, pause)

        if parent.without_review is not None:
            st.markdown("#### Review loop off")
            claims_off = load_claims(conn, parent.without_review.run_id)
            show_no_review_setup(parent.without_review, claims_off, evidence_by_id)

        if parent.with_review is not None and parent.without_review is not None:
            st.markdown("#### Side by side")
            show_comparison(conn, parent.with_review, parent.without_review)


def replay_view() -> None:
    """Pick a saved database and run, then replay its committee."""
    st.caption("Replays saved runs from data/. No model calls, no cost, files are not changed.")
    databases = {path.name: path for path in list_databases()}
    if not databases:
        st.info("No .db files in data/ yet. Run research or a live committee first.")
        return
    database = databases[st.selectbox("Database", list(databases), key="replay_db")]
    try:
        with closing(open_readonly(database)) as conn:
            found = {item.run.run_id: item for item in gathering_runs(conn)}
    except sqlite3.Error as error:
        st.error(f"Could not read {database.name}: {error}")
        return
    if not found:
        st.info(f"{database.name} has no finished committee runs to replay.")
        return
    run_id = st.selectbox(
        "Gathering run", list(found), format_func=lambda key: found[key].label, key="replay_run"
    )
    parent = found[run_id]
    pause = st.slider("Pause between steps (seconds)", 0.0, 2.0, 0.6, 0.1, key="replay_pause")

    replay_key = f"{database.name}:{run_id}"
    if st.button("Replay", type="primary", icon=":material/play_arrow:", key="replay_button"):
        st.session_state["replayed"] = replay_key
        show_replay(database, parent, pause)
    elif st.session_state.get("replayed") == replay_key:
        show_replay(database, parent, pause=0.0)
    else:
        st.info("Press Replay to watch the committee argue, round by round.")


# ---- live ----------------------------------------------------------------------


def new_database_name() -> str:
    """Suggest a fresh file in data/ so a live run never writes into saved runs."""
    return str(DATA_DIR / f"live_{datetime.now().strftime('%Y%m%d_%H%M')}.db")


@dataclass(frozen=True)
class ModelServer:
    """One server that speaks the OpenAI API, configured from the environment."""

    label: str
    base_url: str | None
    api_key: str
    billed: bool
    known_models: tuple[str, ...] | None = None


def model_servers(settings: Settings) -> tuple[list[ModelServer], list[str]]:
    """Return the servers that are fully configured, and notes on half-set ones.

    OpenAI uses OPENAI_API_KEY (and OPENAI_BASE_URL if set). A local server
    such as Ollama needs LOCAL_LLM_BASE_URL and LOCAL_LLM_API_KEY; OpenRouter
    needs OPENROUTER_BASE_URL and OPENROUTER_API_KEY. A server with only one
    of its two variables set is left out, with a note naming the missing one.
    """
    values = settings.values
    servers: list[ModelServer] = []
    notes: list[str] = []
    if values.get("OPENAI_API_KEY"):
        # OpenAI also lists embedding and image models, so keep the planner's list.
        servers.append(
            ModelServer(
                "OpenAI",
                values.get("OPENAI_BASE_URL"),
                values["OPENAI_API_KEY"],
                True,
                CURRENT_OPENAI_MODELS,
            )
        )
    pairs = (
        ("Local", "LOCAL_LLM_BASE_URL", "LOCAL_LLM_API_KEY", False),
        ("OpenRouter", "OPENROUTER_BASE_URL", "OPENROUTER_API_KEY", True),
    )
    for name, url_var, key_var, billed in pairs:
        url, key = values.get(url_var), values.get(key_var)
        if url and key:
            servers.append(ModelServer(f"{name} ({url})", url, key, billed))
        elif url or key:
            missing = key_var if url else url_var
            notes.append(f"{name} is left out because {missing} is not set.")
    return servers, notes


def server_settings(
    settings: Settings, server: ModelServer, model: str | None, timeout: float
) -> Settings:
    """Point the project's OpenAI settings at one server, model, and timeout."""
    return settings.with_values(
        OPENAI_API_KEY=server.api_key,
        OPENAI_BASE_URL=server.base_url,
        OPENAI_MODEL=model,
        OPENAI_TIMEOUT=str(timeout),
    )


@st.cache_data(ttl=300, show_spinner="Loading models from the server...")
def server_models(base_url: str | None, api_key: str, timeout: float) -> list[str]:
    """Return the model ids a server reports, sorted, cached for five minutes."""
    options: dict[str, object] = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        options["base_url"] = base_url
    with OpenAI(**options) as client:
        return sorted(model.id for model in client.models.list())


def run_warnings(snapshot: ResearchSnapshot, comparison: ReviewComparison) -> list[str]:
    """Collect every stage that fell back instead of using the chosen model."""
    warnings = []
    if snapshot.planner_fallback_reason:
        warnings.append(f"Planner used the rule-based plan: {snapshot.planner_fallback_reason}")
    arms = (("review on", comparison.with_review), ("review off", comparison.without_review))
    for arm, result in arms:
        for stage, reason in result.fallbacks.items():
            warnings.append(f"{arm}, {stage}: {reason}")
    return warnings


def run_live(
    symbol: str, database: Path, settings: Settings, model: str
) -> tuple[Path, str, list[str]]:
    """Gather research, then argue it with the review loop on and off.

    Args:
        symbol: Stock symbol to research.
        database: New SQLite file the run is written to.
        settings: Settings already pointed at the chosen server.
        model: Model id used by the planner, Bull, Bear, evaluator, and chair.

    Returns:
        The database path, the new gathering run's id, and any fallback warnings.

    Raises:
        RuntimeError: If the research run could not be saved.
    """
    with st.status(f"Live committee for {symbol} on {model}", expanded=True) as status:
        st.write("Planning and gathering earnings, news, and market data...")
        snapshot = run_research(
            symbol,
            database_path=database,
            planner_provider="openai",
            planner_model=model,
            settings=settings,
        )
        if snapshot.storage_error is not None:
            raise RuntimeError(f"Research ran but could not be saved: {snapshot.storage_error}")
        for source, message in snapshot.gather_errors.items():
            st.warning(f"{source.title()}: {message}")
        st.write("Arguing the evidence with the review loop on, then off...")
        with closing(open_db(database)) as conn:
            comparison = run_review_comparison(
                conn, snapshot.run.run_id, settings, provider="openai", model=model
            )
        status.update(label=f"Live committee for {symbol}: done", state="complete")
    return database, snapshot.run.run_id, run_warnings(snapshot, comparison)


def live_view() -> None:
    """Run the real committee for one symbol on a chosen server and model."""
    settings = load_settings()
    servers, notes = model_servers(settings)
    for note in notes:
        st.caption(note)
    if not servers:
        st.info(
            "Live committee is off because no model server is configured. Set "
            "OPENAI_API_KEY, or LOCAL_LLM_BASE_URL and LOCAL_LLM_API_KEY, or "
            "OPENROUTER_BASE_URL and OPENROUTER_API_KEY (see .env.example), then "
            "restart the app. Committee replay works without any of them."
        )
        return

    by_label = {server.label: server for server in servers}
    server = by_label[st.selectbox("Model server", list(by_label), key="live_server")]
    timeout = st.number_input(
        "Seconds to wait for each model call",
        min_value=1.0,
        value=settings.openai_timeout(),
        step=30.0,
        key="live_timeout",
        help="Local models can need minutes per call. A call that runs out of time "
        "falls back to the template or rules, and the page lists it.",
    )
    try:
        models = server_models(server.base_url, server.api_key, timeout)
        if server.known_models is not None:
            models = [model for model in models if model in server.known_models]
    except Exception as error:  # Show connection and auth failures on the page.
        st.error(f"Could not list models on {server.label}: {error}")
        return
    if not models:
        st.error(f"{server.label} reported no models.")
        return
    configured = settings.values.get("OPENAI_MODEL")
    start = models.index(configured) if configured in models else 0
    model = st.selectbox("Model", models, index=start, key="live_model")

    # A widget's value can only be set before the widget is drawn in a run,
    # so a finished run asks for a fresh file name on the next rerun.
    if st.session_state.pop("live_db_reset", False) or "live_db" not in st.session_state:
        st.session_state["live_db"] = new_database_name()
        st.session_state["live_agreed"] = False
    symbol = st.text_input("Stock symbol", value="AAPL", max_chars=10, key="live_symbol")
    database = Path(st.text_input("New database file", key="live_db"))

    can_run = True
    if database.exists():
        st.warning(f"{database} already exists. Live runs write to a new file only.")
        can_run = False
    elif server.billed:
        st.warning(
            "This makes live model calls (planner, Bull, Bear, evaluator, and verdict) for "
            f"both setups, and your {server.label} account is billed for them."
        )
    else:
        st.warning(
            "This runs every model call on this machine. There is no API bill, but a "
            "full committee makes about 25 calls and can take a long time."
        )
    agreed = st.checkbox("I understand what this run will call", key="live_agreed")
    if st.button(
        "Run live committee", type="primary", disabled=not (agreed and can_run), key="live_run"
    ):
        chosen = server_settings(settings, server, model, timeout)
        try:
            st.session_state["live_result"] = run_live(symbol, database, chosen, model)
        except Exception as error:  # Show provider and data failures on the page.
            st.error(str(error))
            return
        st.session_state["live_db_reset"] = True
        st.rerun()

    result: tuple[Path, str, list[str]] | None = st.session_state.get("live_result")
    if result is not None:
        show_live_result(*result)


def show_live_result(database: Path, parent_id: str, warnings: list[str]) -> None:
    """Hand a finished live run to the replay view, after any fallback warnings."""
    for warning in warnings:
        st.warning(warning)
    with closing(open_readonly(database)) as conn:
        found = [item for item in gathering_runs(conn) if item.run.run_id == parent_id]
    if not found:
        st.error(f"The live run was not found in {database}.")
        return
    st.success(f"Saved to {database}. It also appears under Committee replay.")
    show_replay(database, found[0], pause=0.4)
