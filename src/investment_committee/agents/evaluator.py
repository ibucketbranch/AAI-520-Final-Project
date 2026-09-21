"""Evaluator agent: checks which Bull and Bear claims the evidence supports.

Counts supported vs unsupported claims and sends unsupported ones back with
the reason attached. Serves the "self-reflects to assess quality" agent
function and the evaluator-optimizer workflow pattern.

Stub implementation: a claim is supported when every evidence id it cites
exists in the pool. The real evaluator will also read the claim against the
evidence text; the signatures stay.
"""

from __future__ import annotations

from investment_committee.models import Claim, Evidence

# The three gatherer sources the planner expects to hear from.
_EXPECTED_SOURCES = ("earnings", "news", "market")


def evaluate_claims(claims: list[Claim], evidence: list[Evidence]) -> list[Claim]:
    """Fill in supported and reason for every claim.

    Args:
        claims: Bull and Bear claims, evidence_ids populated.
        evidence: The run's evidence pool the claims cite into.

    Returns:
        The same claims with supported set, and reason set on the
        unsupported ones so the workflow can send them back.
    """
    pool_ids = {item.evidence_id for item in evidence}
    checked: list[Claim] = []
    for claim in claims:
        missing = [eid for eid in claim.evidence_ids if eid not in pool_ids]
        if missing:
            checked.append(
                claim.model_copy(
                    update={
                        "supported": False,
                        "reason": "cites evidence not in the pool: " + ", ".join(missing),
                    }
                )
            )
        else:
            checked.append(claim.model_copy(update={"supported": True}))
    return checked


def reflect(claims: list[Claim], evidence: list[Evidence]) -> tuple[float, list[str]]:
    """Return the drafting step's own confidence and open gaps.

    This is the self-reflection record the memory note stores: confidence is
    the supported share of the evaluated claims, and the gaps name what the
    run went without.

    Args:
        claims: Claims after evaluate_claims() has filled supported.
        evidence: The run's evidence pool.

    Returns:
        (confidence, open_gaps): confidence in [0, 1], 0.0 when there are
        no claims; open_gaps lists missing gatherer sources and the count
        of unsupported claims when there are any.
    """
    gaps: list[str] = []
    seen_sources = {item.source for item in evidence}
    for source in _EXPECTED_SOURCES:
        if source not in seen_sources:
            gaps.append(f"no {source} evidence in the pool")

    if not claims:
        return 0.0, gaps + ["no claims were drafted"]

    unsupported = [c for c in claims if c.supported is False]
    if unsupported:
        gaps.append(f"{len(unsupported)} claim(s) sent back as unsupported")
    confidence = (len(claims) - len(unsupported)) / len(claims)
    return confidence, gaps
