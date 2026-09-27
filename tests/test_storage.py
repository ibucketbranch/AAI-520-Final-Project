"""Tests for the SQLite door: every record round-trips, and the seed path runs once."""

import sqlite3
from pathlib import Path

import pytest

from investment_committee.models import Claim, Evidence, MemoryNote, ModelCall, Run
from investment_committee.storage import (
    finish_run,
    load_claims,
    load_evidence,
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
