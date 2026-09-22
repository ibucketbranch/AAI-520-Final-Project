"""Tests for the Bull, Bear, and evaluator stubs over the shared models."""

from investment_committee.agents.bear import draft_bear_claims
from investment_committee.agents.bull import draft_bull_claims
from investment_committee.agents.evaluator import evaluate_claims, reflect
from investment_committee.models import Evidence, Run


def make_pool():
    run = Run(symbol="AAPL")
    pool = [
        Evidence(
            run_id=run.run_id,
            symbol="AAPL",
            source="earnings",
            title="Revenue beat expectations",
            content="Invented numbers.",
            as_of="2026-09-19",
            reference="fixture:test",
        ),
        Evidence(
            run_id=run.run_id,
            symbol="AAPL",
            source="news",
            title="Product event announced",
            content="Invented event.",
            as_of="2026-09-19",
            reference="fixture:test",
        ),
    ]
    return run, pool


def test_bull_and_bear_draft_one_claim_per_evidence_item():
    _, pool = make_pool()
    bull = draft_bull_claims(pool)
    bear = draft_bear_claims(pool)
    assert len(bull) == len(pool) and len(bear) == len(pool)
    assert all(c.side == "bull" for c in bull)
    assert all(c.side == "bear" for c in bear)
    cited = {eid for c in bull + bear for eid in c.evidence_ids}
    assert cited == {e.evidence_id for e in pool}


def test_evaluator_supports_valid_claims_and_flags_bad_pointers():
    _, pool = make_pool()
    claims = draft_bull_claims(pool)
    tampered = claims[0].model_copy(update={"evidence_ids": ["nonexistent00"]})
    checked = evaluate_claims([tampered] + claims[1:], pool)
    assert checked[0].supported is False
    assert "nonexistent00" in (checked[0].reason or "")
    assert all(c.supported is True for c in checked[1:])
    assert all(c.reason is None for c in checked[1:])


def test_reflect_reports_confidence_and_gaps():
    _, pool = make_pool()  # earnings and news present, market missing
    checked = evaluate_claims(draft_bull_claims(pool), pool)
    confidence, gaps = reflect(checked, pool)
    assert confidence == 1.0
    assert "no market evidence in the pool" in gaps

    tampered = checked[0].model_copy(
        update={"evidence_ids": ["nonexistent00"], "supported": None, "reason": None}
    )
    rechecked = evaluate_claims([tampered, checked[1]], pool)
    confidence, gaps = reflect(rechecked, pool)
    assert confidence == 0.5
    assert any("unsupported" in g for g in gaps)


def test_reflect_with_no_claims_is_zero_confidence():
    _, pool = make_pool()
    confidence, gaps = reflect([], pool)
    assert confidence == 0.0
    assert "no claims were drafted" in gaps
