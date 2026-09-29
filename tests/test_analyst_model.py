"""Tests for the model-backed Bull and Bear drafting, no network calls."""

from types import SimpleNamespace

import pytest

from investment_committee.agents.analyst import (
    AnalystProviderError,
    DraftedClaim,
    DraftedClaims,
    draft_claims_model,
)
from investment_committee.agents.bear import draft_bear_claims_model
from investment_committee.agents.bull import draft_bull_claims_model
from investment_committee.config import ENV_VARS, MissingKeyError, Settings
from investment_committee.models import Claim, Evidence

RUN_ID = "run-test-1"


def settings_with(**values):
    current = {name: None for name in ENV_VARS}
    current.update(values)
    return Settings(values=current)


def pool():
    return [
        Evidence(
            evidence_id=f"ev-{n}",
            run_id=RUN_ID,
            symbol="NFLX",
            source="news",
            title=f"Headline {n}",
            content=f"Body of article {n}.",
            as_of="2026-09-29",
            reference=f"fixture-{n}",
        )
        for n in (1, 2)
    ]


class FakeResponses:
    def __init__(self, parsed):
        self.parsed = parsed
        self.request = None

    def parse(self, **request):
        self.request = request
        return SimpleNamespace(
            output_parsed=self.parsed,
            model="test-openai-model",
            usage=SimpleNamespace(input_tokens=120, output_tokens=40),
        )


class FakeClient:
    def __init__(self, parsed):
        self.responses = FakeResponses(parsed)


class ExplodingClient:
    class responses:
        @staticmethod
        def parse(**request):
            raise RuntimeError("boom")


def parsed_claims(*id_lists):
    return DraftedClaims(
        claims=[
            DraftedClaim(text=f"Claim {n}", evidence_ids=list(ids))
            for n, ids in enumerate(id_lists, start=1)
        ]
    )


def test_happy_path_builds_claims_and_model_call():
    client = FakeClient(parsed_claims(["ev-1"], ["ev-1", "ev-2"]))
    result = draft_claims_model("bull", pool(), settings_with(OPENAI_API_KEY="k"), client=client)
    assert [claim.side for claim in result.claims] == ["bull", "bull"]
    assert all(claim.revision == 0 for claim in result.claims)
    assert result.claims[1].evidence_ids == ["ev-1", "ev-2"]
    assert result.model_call.stage == "bull"
    assert result.model_call.model == "test-openai-model"
    assert result.model_call.prompt_tokens == 120
    assert "ev-1" in client.responses.request["input"]
    assert result.dropped_ids == []


def test_hallucinated_ids_are_dropped():
    client = FakeClient(parsed_claims(["ev-1", "ev-fake"], ["ev-ghost"]))
    result = draft_claims_model("bear", pool(), settings_with(OPENAI_API_KEY="k"), client=client)
    assert len(result.claims) == 1
    assert result.claims[0].evidence_ids == ["ev-1"]
    assert sorted(result.dropped_ids) == ["ev-fake", "ev-ghost"]


def test_all_claims_hallucinated_raises():
    client = FakeClient(parsed_claims(["ev-fake"]))
    with pytest.raises(AnalystProviderError):
        draft_claims_model("bull", pool(), settings_with(OPENAI_API_KEY="k"), client=client)


def test_revise_round_bumps_revision_and_mentions_reason():
    rejected = Claim(
        run_id=RUN_ID,
        side="bull",
        text="Old claim",
        evidence_ids=["ev-1"],
        supported=False,
        reason="cites evidence not in the pool: ev-9",
        revision=0,
    )
    client = FakeClient(parsed_claims(["ev-2"]))
    result = draft_claims_model(
        "bull",
        pool(),
        settings_with(OPENAI_API_KEY="k"),
        revise=[rejected],
        client=client,
    )
    assert result.claims[0].revision == 1
    assert "cites evidence not in the pool" in client.responses.request["input"]


def test_api_error_wrapped():
    with pytest.raises(AnalystProviderError):
        draft_claims_model(
            "bull", pool(), settings_with(OPENAI_API_KEY="k"), client=ExplodingClient()
        )


def test_empty_pool_raises_before_key_check():
    with pytest.raises(AnalystProviderError):
        draft_claims_model("bull", [], settings_with(OPENAI_API_KEY="k"), client=object())


def test_missing_key_raises():
    with pytest.raises(MissingKeyError):
        draft_claims_model("bull", pool(), settings_with(), client=FakeClient(None))


def test_wrappers_set_their_side():
    bull = draft_bull_claims_model(
        pool(), settings_with(OPENAI_API_KEY="k"), client=FakeClient(parsed_claims(["ev-1"]))
    )
    bear = draft_bear_claims_model(
        pool(), settings_with(OPENAI_API_KEY="k"), client=FakeClient(parsed_claims(["ev-1"]))
    )
    assert bull.claims[0].side == "bull"
    assert bull.model_call.stage == "bull"
    assert bear.claims[0].side == "bear"
    assert "pessimistic" in bear.model_call.prompt
