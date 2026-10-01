"""Bear analyst: argues the pessimistic case from the evidence pool.

Every claim it makes carries a pointer back to the evidence item it came
from, so the evaluator can check it. Serves the Agent Functions rubric items
and feeds the evaluator-optimizer workflow.

Two paths: draft_bear_claims is the templated no-model fallback (one claim
per evidence item), and draft_bear_claims_model asks the model, degrading
to the template with a recorded fallback_reason when no key or the API
fails, the same story as the planner.
"""

from __future__ import annotations

from typing import Any

from investment_committee.agents.analyst import (
    AnalystProvider,
    DraftingResult,
    draft_claims_with_fallback,
)
from investment_committee.config import Settings
from investment_committee.models import Claim, Evidence


def draft_bear_claims(evidence: list[Evidence]) -> list[Claim]:
    """Draft the pessimistic case: one templated claim per evidence item.

    Args:
        evidence: The run's evidence pool, any mix of sources.

    Returns:
        Claims with side "bear", each pointing at the one evidence item it
        restates. The template reads the item's title as a risk; the model
        path argues instead of restating.
    """
    claims: list[Claim] = []
    for item in evidence:
        claims.append(
            Claim(
                run_id=item.run_id,
                side="bear",
                text=f"Risk signal for {item.symbol}: {item.title}.",
                evidence_ids=[item.evidence_id],
            )
        )
    return claims


def draft_bear_claims_model(
    evidence: list[Evidence],
    settings: Settings,
    *,
    provider: AnalystProvider = "openai",
    revise: list[Claim] | None = None,
    keep: list[Claim] | None = None,
    revision: int = 0,
    model: str | None = None,
    client: Any | None = None,
) -> DraftingResult:
    """Draft the pessimistic case, falling back to the template when needed.

    Same contract as draft_claims_with_fallback with side "bear" and the
    template above as the degrade path.
    """
    return draft_claims_with_fallback(
        "bear",
        draft_bear_claims,
        evidence,
        settings,
        provider=provider,
        revise=revise,
        keep=keep,
        revision=revision,
        model=model,
        client=client,
    )
