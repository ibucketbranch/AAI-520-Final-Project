"""Tests for the shared record shapes: defaults, and the rules they enforce."""

import pytest
from pydantic import ValidationError

from investment_committee.models import Claim, Evidence, MemoryNote, Run


def test_ids_and_timestamps_are_filled_in():
    run = Run(symbol="AAPL")
    other = Run(symbol="AAPL")
    assert run.run_id and run.run_id != other.run_id
    assert run.started_at.endswith("+00:00")
    assert run.finished_at is None and run.memo is None


def test_claim_must_point_at_evidence():
    # ADR-0002: every claim carries a pointer to the evidence it came from.
    with pytest.raises(ValidationError):
        Claim(run_id="r1", side="bull", text="Revenue grew.", evidence_ids=[])
    claim = Claim(run_id="r1", side="bull", text="Revenue grew.", evidence_ids=["ev-001"])
    assert claim.supported is None and claim.revision == 0


def test_source_and_side_are_limited_to_the_known_labels():
    with pytest.raises(ValidationError):
        Evidence(
            run_id="r1",
            symbol="AAPL",
            source="twitter",
            title="t",
            content="c",
            as_of="2026-09-01",
            reference="x",
        )
    with pytest.raises(ValidationError):
        Claim(run_id="r1", side="neutral", text="x", evidence_ids=["ev-001"])


def test_confidence_stays_between_zero_and_one():
    with pytest.raises(ValidationError):
        MemoryNote(run_id="r1", symbol="AAPL", confidence=1.5, open_gaps=[], lesson="x")
    note = MemoryNote(
        run_id="r1", symbol="AAPL", confidence=0.7, open_gaps=["no guidance"], lesson="x"
    )
    assert note.confidence == 0.7
