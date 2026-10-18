"""Tests for the SQLite door: every record round-trips, and the seed path runs once."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from investment_committee.models import Claim, Evidence, MemoryNote, ModelCall, Run
from investment_committee.storage import (
    finish_run,
    load_claims,
    load_evidence,
    load_fallbacks,
    load_latest_note,
    load_model_calls,
    load_run,
    open_db,
    save_claim,
    save_evidence,
    save_memory_note,
    save_model_call,
    save_run,
    save_run_with_evidence,
    seed_from_json,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_evidence.json"


@pytest.fixture()
def conn():
    """A fresh in-memory database with one run already saved."""
    conn = open_db(":memory:")
    save_run(conn, Run(run_id="r1", symbol="AAPL"))
    return conn


def test_open_db_creates_the_file_and_keeps_data_across_reopen(tmp_path):
    path = tmp_path / "nested" / "committee.db"
    first = open_db(path)
    save_run(first, Run(run_id="r1", symbol="TSLA"))
    first.close()
    assert path.exists()
    again = open_db(path)  # second open must not wipe or error on existing tables
    run = load_run(again, "r1")
    assert run is not None and run.symbol == "TSLA"


def test_run_round_trip_and_finish(conn):
    run = load_run(conn, "r1")
    assert run is not None
    assert run.with_review is True and run.memo is None
    finish_run(conn, "r1", memo="Do not buy.", finished_at="2026-09-15T00:00:00+00:00")
    run = load_run(conn, "r1")
    assert run is not None
    assert run.memo == "Do not buy." and run.finished_at is not None
    assert load_run(conn, "missing") is None


def test_finish_run_records_the_degraded_stages(conn):
    assert load_fallbacks(conn, "r1") == {}
    finish_run(
        conn,
        "r1",
        memo="Verdict: none.",
        finished_at="2026-09-15T00:00:00+00:00",
        fallbacks={"evaluator round 1": "no API key"},
    )
    assert load_fallbacks(conn, "r1") == {"evaluator round 1": "no API key"}
    assert load_fallbacks(conn, "missing") == {}


def test_old_database_is_migrated_without_losing_records(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, with_review INTEGER NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, memo TEXT
        );
        INSERT INTO runs VALUES ('old', 'AAPL', 1, '2026-09-01', NULL, 'Saved memo');
    """)
    old.close()
    for _ in range(2):
        conn = open_db(path)
        try:
            run = load_run(conn, "old")
            assert run.memo == "Saved memo"
            assert run.parent_run_id is None
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(runs)")]
            assert columns.count("parent_run_id") == 1
            assert columns.count("fallbacks") == 1
        finally:
            conn.close()
    conn = open_db(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            save_run(conn, Run(symbol="AAPL", parent_run_id="missing"))
    finally:
        conn.close()


def test_committee_siblings_keep_their_claims_separate(conn):
    evidence = Evidence(
        evidence_id="shared-evidence",
        run_id="r1",
        symbol="AAPL",
        source="market",
        title="Price",
        content="$100",
        as_of="2026-10-02",
        reference="fixture",
    )
    save_evidence(conn, [evidence])
    for run_id, review in (("reviewed", True), ("baseline", False)):
        run = Run(run_id=run_id, symbol="AAPL", parent_run_id="r1", with_review=review)
        save_run(conn, run)
        assert load_run(conn, run_id) == run
        claim = Claim(run_id=run_id, side="bull", text="A claim", evidence_ids=["shared-evidence"])
        save_claim(conn, claim)
        assert load_claims(conn, run_id) == [claim]
        call = ModelCall(run_id=run_id, stage="bull", model="test", prompt="p", response="r")
        save_model_call(conn, call)
        assert load_model_calls(conn, run_id) == [call]
        assert load_evidence(conn, run_id) == []
    siblings = conn.execute("SELECT run_id FROM runs WHERE parent_run_id = ?", ("r1",)).fetchall()
    assert {row["run_id"] for row in siblings} == {"reviewed", "baseline"}
    assert load_claims(conn, "r1") == []
    assert load_evidence(conn, "r1") == [evidence]
    with pytest.raises(sqlite3.IntegrityError):
        save_run(conn, Run(symbol="AAPL", parent_run_id="missing"))


def test_two_sessions_can_migrate_the_same_old_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, with_review INTEGER NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, memo TEXT
    )""")
    old.close()

    def connect_and_close(_):
        conn = open_db(path)
        try:
            return [row["name"] for row in conn.execute("PRAGMA table_info(runs)")]
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(connect_and_close, range(2)))
    assert all(columns.count("parent_run_id") == 1 for columns in results)


def test_evidence_round_trip_keeps_order(conn):
    items = [
        Evidence(
            run_id="r1",
            symbol="AAPL",
            source="earnings",
            title="Revenue",
            content="up",
            as_of="2026-07-30",
            reference="yfinance:AAPL:income_stmt",
        ),
        Evidence(
            run_id="r1",
            symbol="AAPL",
            source="market",
            title="RSI(14)",
            content="61",
            as_of="2026-09-11",
            reference="yfinance:AAPL:history",
        ),
    ]
    save_evidence(conn, items)
    loaded = load_evidence(conn, "r1")
    assert loaded == items


def test_evidence_for_an_unknown_run_is_rejected(conn):
    item = Evidence(
        run_id="nope",
        symbol="AAPL",
        source="news",
        title="t",
        content="c",
        as_of="2026-09-01",
        reference="x",
    )
    with pytest.raises(sqlite3.IntegrityError):
        save_evidence(conn, [item])


def test_saving_a_claim_again_records_the_verdict(conn):
    claim = Claim(run_id="r1", side="bear", text="Margins fell.", evidence_ids=["ev-001", "ev-002"])
    save_claim(conn, claim)
    claim.supported = False
    claim.reason = "ev-002 is about EPS, not margins."
    save_claim(conn, claim)
    loaded = load_claims(conn, "r1")
    assert len(loaded) == 1
    assert loaded[0] == claim
    assert loaded[0].evidence_ids == ["ev-001", "ev-002"]


def test_latest_note_is_the_newest_for_that_symbol(conn):
    save_run(conn, Run(run_id="r2", symbol="AAPL"))
    save_memory_note(
        conn,
        MemoryNote(
            run_id="r1",
            symbol="AAPL",
            confidence=0.4,
            open_gaps=["no guidance"],
            lesson="old",
            created_at="2026-09-01T00:00:00+00:00",
        ),
    )
    save_memory_note(
        conn,
        MemoryNote(
            run_id="r2",
            symbol="AAPL",
            confidence=0.8,
            open_gaps=[],
            lesson="new",
            created_at="2026-09-10T00:00:00+00:00",
        ),
    )
    note = load_latest_note(conn, "AAPL")
    assert note is not None and note.lesson == "new" and note.open_gaps == []
    assert load_latest_note(conn, "TSLA") is None


def test_model_call_round_trip(conn):
    call = ModelCall(
        run_id="r1",
        stage="bull",
        model="stub",
        prompt="p",
        response="r",
        prompt_tokens=12,
        completion_tokens=30,
        latency_ms=250,
    )
    save_model_call(conn, call)
    assert load_model_calls(conn, "r1") == [call]


def test_run_evidence_and_model_call_are_saved_together():
    conn = open_db(":memory:")
    run = Run(run_id="r2", symbol="AAPL")
    evidence = Evidence(
        run_id="r2",
        symbol="AAPL",
        source="market",
        title="Price",
        content="$100.00",
        as_of="2026-09-26",
        reference="fixture:market",
    )
    call = ModelCall(
        run_id="r2",
        stage="planner",
        model="test-model",
        prompt="plan AAPL",
        response="market first",
    )

    save_run_with_evidence(conn, run, [evidence], [call])

    assert load_run(conn, "r2") == run
    assert load_evidence(conn, "r2") == [evidence]
    assert load_model_calls(conn, "r2") == [call]


def test_model_call_failure_rolls_back_the_run_and_evidence():
    conn = open_db(":memory:")
    run = Run(run_id="r2", symbol="AAPL")
    evidence = Evidence(
        run_id="r2",
        symbol="AAPL",
        source="market",
        title="Price",
        content="$100.00",
        as_of="2026-09-26",
        reference="fixture:market",
    )
    wrong_call = ModelCall(
        run_id="another-run",
        stage="planner",
        model="test-model",
        prompt="plan AAPL",
        response="market first",
    )

    with pytest.raises(sqlite3.IntegrityError):
        save_run_with_evidence(conn, run, [evidence], [wrong_call])

    assert load_run(conn, "r2") is None
    assert load_evidence(conn, "r2") == []


def test_seed_from_json_runs_once():
    conn = open_db(":memory:")
    assert seed_from_json(conn, FIXTURE_PATH) == 4
    assert seed_from_json(conn, FIXTURE_PATH) == 0
    run = load_run(conn, "sample-aapl-001")
    assert run is not None and run.symbol == "AAPL"
    sources = {e.source for e in load_evidence(conn, "sample-aapl-001")}
    assert sources == {"earnings", "news", "market"}
