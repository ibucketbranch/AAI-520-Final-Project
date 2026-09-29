"""Bear analyst: argues the pessimistic case from the evidence pool.

Every claim it makes carries a pointer back to the evidence item it came
from, so the evaluator can check it. Serves the Agent Functions rubric items
and feeds the evaluator-optimizer workflow.

Stub implementation: one templated claim per evidence item, no model call.
The signature is the contract; the Oct 6 milestone swaps the template for a
real model behind the same function.
"""

from __future__ import annotations

from typing import Any

from investment_committee.agents.analyst import DraftingResult, draft_claims_model
from investment_committee.config import Settings
from investment_committee.models import Claim, Evidence


def draft_bear_claims(evidence: list[Evidence]) -> list[Claim]:
    """Draft the pessimistic case: one claim per evidence item.

    Args:
        evidence: The run's evidence pool, any mix of sources.

    Returns:
        Claims with side "bear", each pointing at the one evidence item it
        restates. The stub reads the item's title as a risk; the real
        analyst will argue, not restate.
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
    revise: list[Claim] | None = None,
    model: str | None = None,
    client: Any | None = None,
) -> DraftingResult:
    """Draft the pessimistic case with a model call.

    Same contract as draft_claims_model with side "bear"; the templated
    draft_bear_claims above stays as the no-key fallback.
    """
    return draft_claims_model("bear", evidence, settings, revise=revise, model=model, client=client)
