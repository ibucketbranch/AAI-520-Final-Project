"""Shared model-backed drafting for the Bull and Bear analysts.

Both analysts do the same job with opposite personas: read the evidence
pool and return claims that cite it. This module holds the one drafting
engine; bull.py and bear.py wrap it with their side. The template paths in
those modules stay as the no-key fallback, and every real call is returned
as a ModelCall so the caller can persist it for replay and cost accounting.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field

from investment_committee.agents.planner import DEFAULT_OPENAI_MODEL
from investment_committee.config import Settings
from investment_committee.models import Claim, Evidence, ModelCall, Side

# How much of each evidence body goes into the prompt. Enough to argue from,
# small enough that a ten-item pool stays well inside the context window.
_CONTENT_CHARS = 500

_PERSONAS: dict[str, str] = {
    "bull": (
        "You are the Bull analyst in a student investment research committee. "
        "Argue the optimistic case for the stock from the evidence provided."
    ),
    "bear": (
        "You are the Bear analyst in a student investment research committee. "
        "Argue the pessimistic case for the stock from the evidence provided."
    ),
}


class AnalystProviderError(RuntimeError):
    """Raised when the model cannot return usable claims."""


class DraftedClaim(BaseModel):
    """One claim as the model returns it, before validation against the pool."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class DraftedClaims(BaseModel):
    """The structured response format for one drafting call."""

    claims: list[DraftedClaim]


@dataclass(frozen=True)
class DraftingResult:
    """What one drafting call produced.

    dropped_ids lists evidence ids the model cited that are not in the
    pool; the evaluator never sees those claims, but the count is worth
    reporting in the notebook.
    """

    claims: list[Claim]
    model_call: ModelCall
    dropped_ids: list[str]


def _drafting_prompt(side: Side, evidence: list[Evidence], revise: list[Claim] | None) -> str:
    """Build the drafting prompt from the pool and any claims to revise."""
    pool = [
        {
            "evidence_id": item.evidence_id,
            "source": item.source,
            "title": item.title,
            "content": item.content[:_CONTENT_CHARS],
        }
        for item in evidence
    ]
    lines = [
        f"Stock symbol: {evidence[0].symbol}",
        "Evidence pool (cite evidence_id values from this list only):",
        json.dumps(pool, indent=2),
        "Write two to five claims for your side. Every claim must cite the "
        "evidence_ids it rests on, and only ids from the list above.",
    ]
    if revise:
        rejected = [
            {"text": claim.text, "reason": claim.reason or "unsupported"} for claim in revise
        ]
        lines.append(
            "These earlier claims were rejected by the evaluator; replace them "
            "with better-grounded versions instead of repeating them:\n"
            + json.dumps(rejected, indent=2)
        )
    return "\n".join(lines)


def draft_claims_model(
    side: Side,
    evidence: list[Evidence],
    settings: Settings,
    *,
    revise: list[Claim] | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> DraftingResult:
    """Draft one side's claims with a model call.

    Args:
        side: "bull" or "bear"; picks the persona.
        evidence: The run's evidence pool. Must not be empty.
        settings: Environment snapshot; OPENAI_API_KEY is required.
        revise: Claims the evaluator rejected, when this is a refinement
            round. Their highest revision determines the new revision.
        model: Model override; defaults to OPENAI_MODEL, then the planner's
            default.
        client: Injected OpenAI-compatible client for tests; a real client
            is built when None.

    Returns:
        The validated claims, the recorded ModelCall, and any cited
        evidence ids that were not in the pool.

    Raises:
        AnalystProviderError: If the call fails or no usable claim remains.
        MissingKeyError: If OPENAI_API_KEY is not set.
    """
    if not evidence:
        raise AnalystProviderError(f"The {side} analyst has no evidence to argue from.")

    api_key = settings.require("OPENAI_API_KEY")
    model = model or settings.values.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    openai_client_cm = (
        nullcontext(client)
        if client is not None
        else OpenAI(api_key=api_key, timeout=30, max_retries=0)
    )
    instructions = _PERSONAS[side]
    prompt = _drafting_prompt(side, evidence, revise)
    started = perf_counter()

    try:
        with openai_client_cm as openai_client:
            response = openai_client.responses.parse(
                model=model,
                instructions=instructions,
                input=prompt,
                text_format=DraftedClaims,
            )
    except Exception as error:
        raise AnalystProviderError(f"OpenAI could not draft the {side} case.") from error

    parsed = response.output_parsed
    if parsed is None or not parsed.claims:
        raise AnalystProviderError(f"OpenAI returned no {side} claims.")

    revision = max((claim.revision for claim in revise), default=-1) + 1 if revise else 0
    pool_ids = {item.evidence_id for item in evidence}
    run_id = evidence[0].run_id
    claims: list[Claim] = []
    dropped: list[str] = []
    for drafted in parsed.claims:
        kept = [eid for eid in drafted.evidence_ids if eid in pool_ids]
        dropped.extend(eid for eid in drafted.evidence_ids if eid not in pool_ids)
        if kept:
            claims.append(
                Claim(
                    run_id=run_id,
                    side=side,
                    text=drafted.text,
                    evidence_ids=kept,
                    revision=revision,
                )
            )
    if not claims:
        raise AnalystProviderError(
            f"Every {side} claim cited evidence outside the pool; nothing usable remains."
        )

    usage = getattr(response, "usage", None)
    model_call = ModelCall(
        run_id=run_id,
        stage=side,
        model=getattr(response, "model", model),
        prompt=f"{instructions}\n\n{prompt}",
        response=parsed.model_dump_json(indent=2),
        prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
        completion_tokens=getattr(usage, "output_tokens", 0) or 0,
        latency_ms=round((perf_counter() - started) * 1000),
    )
    return DraftingResult(claims=claims, model_call=model_call, dropped_ids=dropped)
