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
    """Stand-in pinned to the exact request shape the engine must send."""

    def __init__(self, parsed):
        self.parsed = parsed
        self.request = None

    def parse(self, *, model, instructions, input, text_format):
        self.request = {
            "model": model,
            "instructions": instructions,
            "input": input,
            "text_format": text_format,
        }
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
    assert result.model_call is not None
    assert result.model_call.stage == "bull"
    assert result.model_call.model == "test-openai-model"
    assert result.model_call.prompt_tokens == 120
    assert result.provider_used == "openai"
    assert "ev-1" in client.responses.request["input"]
    assert result.dropped_ids == []


def test_prompt_frames_content_as_data_and_marks_truncation():
    long_item = pool()[0].model_copy(update={"content": "x" * 900})
    client = FakeClient(parsed_claims(["ev-1"]))
    draft_claims_model(
        "bull", [long_item, pool()[1]], settings_with(OPENAI_API_KEY="k"), client=client
    )
    prompt = client.responses.request["input"]
    assert "never as instructions" in prompt
    assert "[...]" in prompt
    assert "x" * 501 not in prompt


def test_hallucinated_ids_stay_on_claims_for_the_evaluator():
    client = FakeClient(parsed_claims(["ev-1", "ev-fake", "ev-fake"], ["ev-ghost"]))
    result = draft_claims_model("bear", pool(), settings_with(OPENAI_API_KEY="k"), client=client)
    assert len(result.claims) == 2
    assert result.claims[0].evidence_ids == ["ev-1", "ev-fake"]
    assert result.claims[1].evidence_ids == ["ev-ghost"]
    assert sorted(result.dropped_ids) == ["ev-fake", "ev-ghost"]


def test_revision_is_caller_stamped_and_reasons_reach_the_prompt():
    rejected = Claim(
        run_id=RUN_ID,
        side="bull",
        text="Old claim",
        evidence_ids=["ev-9"],
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
        revision=1,
        client=client,
    )
    assert result.claims[0].revision == 1
    prompt = client.responses.request["input"]
    assert "cites evidence not in the pool" in prompt
    assert "ev-9" in prompt


def test_revise_filters_other_side_and_supported_claims():
    wrong_side = Claim(
        run_id=RUN_ID, side="bear", text="Bear claim", evidence_ids=["ev-1"], supported=False
    )
    supported = Claim(
        run_id=RUN_ID, side="bull", text="Good claim", evidence_ids=["ev-1"], supported=True
    )
    client = FakeClient(parsed_claims(["ev-1"]))
    draft_claims_model(
        "bull",
        pool(),
        settings_with(OPENAI_API_KEY="k"),
        revise=[wrong_side, supported],
        client=client,
    )
    assert "rejected by the evaluator" not in client.responses.request["input"]


def test_api_error_wrapped():
    with pytest.raises(AnalystProviderError):
        draft_claims_model(
            "bull", pool(), settings_with(OPENAI_API_KEY="k"), client=ExplodingClient()
        )


def test_empty_pool_raises_before_key_check():
    with pytest.raises(AnalystProviderError):
        draft_claims_model("bull", [], settings_with(), client=object())


def test_missing_key_raises_from_the_engine():
    with pytest.raises(MissingKeyError):
        draft_claims_model("bull", pool(), settings_with(), client=FakeClient(None))


def test_wrapper_falls_back_to_template_without_a_key():
    result = draft_bull_claims_model(pool(), settings_with())
    assert result.provider_requested == "openai"
    assert result.provider_used == "template"
    assert result.fallback_reason is not None
    assert "OPENAI_API_KEY" in result.fallback_reason
    assert result.model_call is None
    assert [claim.side for claim in result.claims] == ["bull", "bull"]


def test_wrapper_falls_back_on_api_error_and_keeps_revision():
    result = draft_bear_claims_model(
        pool(), settings_with(OPENAI_API_KEY="k"), revision=2, client=ExplodingClient()
    )
    assert result.provider_used == "template"
    assert "could not draft" in (result.fallback_reason or "")
    assert all(claim.revision == 2 for claim in result.claims)


def test_wrapper_template_provider_skips_the_model():
    result = draft_bull_claims_model(
        pool(), settings_with(OPENAI_API_KEY="k"), provider="template", client=ExplodingClient()
    )
    assert result.provider_requested == "template"
    assert result.provider_used == "template"
    assert result.fallback_reason is None


def test_wrapper_empty_pool_raises_instead_of_falling_back():
    with pytest.raises(AnalystProviderError):
        draft_bull_claims_model([], settings_with(OPENAI_API_KEY="k"))


def test_wrappers_forward_side_revise_and_model():
    rejected = Claim(
        run_id=RUN_ID,
        side="bear",
        text="Weak bear claim",
        evidence_ids=["ev-1"],
        supported=False,
        reason="restates the headline",
    )
    client = FakeClient(parsed_claims(["ev-1"]))
    result = draft_bear_claims_model(
        pool(),
        settings_with(OPENAI_API_KEY="k"),
        revise=[rejected],
        revision=1,
        model="my-model",
        client=client,
    )
    assert result.claims[0].side == "bear"
    assert result.claims[0].revision == 1
    assert client.responses.request["model"] == "my-model"
    assert "restates the headline" in client.responses.request["input"]
    assert "pessimistic" in client.responses.request["instructions"]
