"""Tests for the deterministic planner and its memory handoff."""

import pytest

from investment_committee.agents.planner import build_plan, normalize_symbol
from investment_committee.models import MemoryNote


def test_plan_normalizes_symbol_and_requests_all_sources():
    plan = build_plan(" aapl ")
    assert plan.symbol == "AAPL"
    assert [task.source for task in plan.tasks] == ["earnings", "news", "market"]
    assert plan.memory_lesson is None


def test_memory_gap_moves_that_source_to_the_front():
    note = MemoryNote(
        run_id="previous",
        symbol="AAPL",
        confidence=0.6,
        open_gaps=["No market evidence in the pool"],
        lesson="Check price momentum first next time.",
    )
    plan = build_plan("AAPL", note)
    assert [task.source for task in plan.tasks] == ["market", "earnings", "news"]
    assert plan.tasks[0].reason.startswith("Revisit the market gap")
    assert plan.memory_lesson == note.lesson


@pytest.mark.parametrize("symbol", ["", "   ", "$AAPL", "AAPL/US"])
def test_invalid_symbols_are_rejected(symbol):
    with pytest.raises(ValueError):
        normalize_symbol(symbol)


def test_memory_note_must_match_the_requested_symbol():
    note = MemoryNote(
        run_id="previous",
        symbol="TSLA",
        confidence=0.5,
        open_gaps=[],
        lesson="Collect guidance.",
    )
    with pytest.raises(ValueError, match="different stock symbol"):
        build_plan("AAPL", note)
