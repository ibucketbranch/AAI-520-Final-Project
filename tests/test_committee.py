"""Tests for the committee loop, no network calls."""

from types import SimpleNamespace

import pytest

from investment_committee.agents.analyst import DraftedClaim, DraftedClaims
from investment_committee.agents.evaluator import ClaimVerdict
from investment_committee.config import ENV_VARS, Settings
from investment_committee.models import Evidence, Run
from investment_committee.storage import (
    load_claims,
    load_latest_note,
    load_run,
    open_db,
    save_run,
    save_run_with_evidence,
)
from investment_committee.workflows.evaluator_optimizer import (
    CommitteeVerdict,
    run_committee,
    run_committee_from_storage,
)


def settings_with(**values):
    current = {name: None for name in ENV_VARS}
    current.update(values)
    return Settings(values=current)


def make_run(**overrides):
    defaults = {"symbol": "NFLX"}
    defaults.update(overrides)
    return Run(**defaults)


def pool(run_id):
    return [
        Evidence(
            evidence_id=f"ev-{n}",
            run_id=run_id,
            symbol="NFLX",
            source=source,
            title=f"Headline {n}",
            content=f"Body of article {n}.",
            as_of="2026-09-29",
            reference=f"fixture-{n}",
        )
        for n, source in ((1, "news"), (2, "market"))
    ]


class RoutingFakeResponses:
    """Dispatch on the requested schema: drafts, verdicts, or the decision."""

    def __init__(self, drafts=(), verdicts=(), decisions=()):
        self.drafts = list(drafts)
        self.verdicts = list(verdicts)
        self.decisions = list(decisions)
        self.requests = []

    def parse(self, *, model, instructions, input, text_format):
        self.requests.append(
            {
                "model": model,
                "instructions": instructions,
                "input": input,
                "text_format": text_format,
            }
        )
        if text_format is DraftedClaims:
            parsed = self.drafts.pop(0)
        elif text_format is ClaimVerdict:
            parsed = self.verdicts.pop(0)
        elif text_format is CommitteeVerdict:
            parsed = self.decisions.pop(0)
        else:
            raise AssertionError(f"unexpected schema {text_format}")
        return SimpleNamespace(
            output_parsed=parsed,
            model="test-model",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


class RoutingFakeClient:
    def __init__(self, **queues):
        self.responses = RoutingFakeResponses(**queues)


def one_claim(*ids, text="A claim"):
    return DraftedClaims(claims=[DraftedClaim(text=text, evidence_ids=list(ids))])


def test_refinement_round_fires_and_verdict_is_a_model_call():
    run = make_run()
    client = RoutingFakeClient(
        drafts=[
            one_claim("ev-1", text="Bull argument"),
            one_claim("ev-fake", text="Bear argument"),
            one_claim("ev-2", text="Bear argument, grounded"),
        ],
        verdicts=[
            ClaimVerdict(supported=True, reason="matches the article"),
            ClaimVerdict(supported=True, reason="matches the article"),
            ClaimVerdict(supported=True, reason="matches the numbers"),
        ],
        decisions=[CommitteeVerdict(side="bear", reason="the risk case is stronger")],
    )
    result = run_committee(run, pool(run.run_id), settings_with(OPENAI_API_KEY="k"), client=client)
    assert result.rounds == 2
    assert result.verdict == "bear"
    assert "risk case" in result.verdict_reason
    sides = sorted((claim.side, claim.revision) for claim in result.claims)
    assert sides == [("bear", 1), ("bull", 0)]
    assert all(claim.supported for claim in result.claims)
    assert len(result.all_claims) == 4
    stages = [call.stage for call in result.model_calls]
    assert stages.count("bull") == 1
    assert stages.count("bear") == 2
    assert stages.count("evaluator") == 3
    assert stages.count("verdict") == 1
    assert result.dropped_ids == ["ev-fake"]
    assert "Verdict: bear" in result.memo
    assert "bear" in result.note.lesson


def test_with_review_false_skips_refinement():
    run = make_run(with_review=False)
    client = RoutingFakeClient(
        drafts=[one_claim("ev-1"), one_claim("ev-fake")],
        verdicts=[ClaimVerdict(supported=True, reason="fine")],
        decisions=[CommitteeVerdict(side="bull", reason="only the bull case held")],
    )
    result = run_committee(run, pool(run.run_id), settings_with(OPENAI_API_KEY="k"), client=client)
    assert result.rounds == 1
    assert client.responses.drafts == []
    unsupported = [claim for claim in result.claims if claim.supported is False]
    assert len(unsupported) == 1
    assert unsupported[0].side == "bear"


def test_max_rounds_caps_a_stubborn_side():
    run = make_run()
    client = RoutingFakeClient(
        drafts=[
            one_claim("ev-1"),
            one_claim("ev-fake"),
            one_claim("ev-fake", text="Still ungrounded"),
        ],
        verdicts=[
            ClaimVerdict(supported=True, reason="fine"),
            ClaimVerdict(supported=True, reason="fine"),
        ],
        decisions=[CommitteeVerdict(side="bull", reason="bear never grounded its case")],
    )
    result = run_committee(
        run, pool(run.run_id), settings_with(OPENAI_API_KEY="k"), max_rounds=2, client=client
    )
    assert result.rounds == 2
    assert any(claim.supported is False for claim in result.claims)
    assert result.verdict == "bull"


def test_template_provider_runs_offline_with_no_verdict():
    run = make_run()
    result = run_committee(run, pool(run.run_id), settings_with(), provider="template")
    assert result.verdict == "none"
    assert result.verdict_reason == "no model available"
    assert result.rounds == 1
    assert result.model_calls == []
    assert all(claim.supported for claim in result.claims)
    assert "Diagnostics:" in result.memo
    assert result.fallbacks == {}


def test_openai_without_key_degrades_every_stage_and_records_it():
    run = make_run()
    result = run_committee(run, pool(run.run_id), settings_with(), provider="openai")
    assert result.verdict == "none"
    assert "bull" in result.fallbacks
    assert "bear" in result.fallbacks
    assert "evaluator round 1" in result.fallbacks
    assert "verdict" in result.fallbacks
    assert result.model_calls == []
    assert all(claim.supported for claim in result.claims)


def test_storage_adapter_persists_the_deliberation(tmp_path):
    db = tmp_path / "committee.db"
    run = make_run()
    with open_db(db) as conn:
        save_run_with_evidence(conn, run, pool(run.run_id), [])
        result = run_committee_from_storage(conn, run.run_id, settings_with(), provider="template")
        stored_claims = load_claims(conn, run.run_id)
        stored_run = load_run(conn, run.run_id)
        note = load_latest_note(conn, "NFLX")
    assert len(stored_claims) == len(result.all_claims)
    assert stored_run is not None
    assert stored_run.memo is not None and stored_run.memo.startswith("Verdict: none")
    assert stored_run.finished_at is not None
    assert note is not None
    assert note.run_id == run.run_id


def test_storage_adapter_rejects_unknown_run(tmp_path):
    with open_db(tmp_path / "empty.db") as conn:
        with pytest.raises(ValueError):
            run_committee_from_storage(conn, "missing-run", settings_with())


def test_redraft_that_repeats_kept_claims_is_deduped():
    """A model that redrafts everything must not duplicate the survivors.

    Caught live on 2026-09-30: the bull redraft repeated the kept revenue,
    EPS, and RSI claims and the memo listed them twice.
    """
    run = make_run()
    client = RoutingFakeClient(
        drafts=[
            DraftedClaims(
                claims=[
                    DraftedClaim(text="Revenue grew", evidence_ids=["ev-1"]),
                    DraftedClaim(text="Bad bull claim", evidence_ids=["ev-fake"]),
                ]
            ),
            one_claim("ev-2", text="Bear argument"),
            DraftedClaims(
                claims=[
                    DraftedClaim(text="Revenue grew", evidence_ids=["ev-1"]),
                    DraftedClaim(text="A grounded replacement", evidence_ids=["ev-2"]),
                ]
            ),
        ],
        verdicts=[
            ClaimVerdict(supported=True, reason="fine"),
            ClaimVerdict(supported=True, reason="fine"),
            ClaimVerdict(supported=True, reason="fine"),
            ClaimVerdict(supported=True, reason="fine"),
            ClaimVerdict(supported=True, reason="fine"),
        ],
        decisions=[CommitteeVerdict(side="bull", reason="growth case held")],
    )
    result = run_committee(run, pool(run.run_id), settings_with(OPENAI_API_KEY="k"), client=client)
    bull_texts = [claim.text for claim in result.claims if claim.side == "bull"]
    assert bull_texts.count("Revenue grew") == 1
    assert "A grounded replacement" in bull_texts
    assert "Bad bull claim" not in bull_texts
    revise_requests = [
        request["input"]
        for request in client.responses.requests
        if "rejected by the evaluator" in request["input"]
    ]
    assert len(revise_requests) == 1
    assert "do not repeat" in revise_requests[0]
    assert "Revenue grew" in revise_requests[0]


def test_storage_adapter_follows_parent_run_evidence(tmp_path):
    """A committee run pointing at a gathering run argues from the parent's pool."""
    db = tmp_path / "parent.db"
    with open_db(db) as conn:
        gather = make_run()
        save_run_with_evidence(conn, gather, pool(gather.run_id), [])
        child = Run(symbol="NFLX", with_review=False, parent_run_id=gather.run_id)
        save_run(conn, child)
        result = run_committee_from_storage(
            conn, child.run_id, settings_with(), provider="template"
        )
    assert result.claims
    cited = {eid for claim in result.claims for eid in claim.evidence_ids}
    assert cited == {"ev-1", "ev-2"}
    assert result.rounds == 1
