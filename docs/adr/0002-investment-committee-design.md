# ADR-0002: The AI Investment Committee is the project

Status: Accepted 2026-09-13

## Context

Two-person team (Michael Valderrama, Guna Pasupathy), six weeks to the final notebook, and a rubric that grades four agent functions, three workflow patterns, and code quality. The assignment fixes the project: a multi-agent Investment Research Agent with four agent functions and three named workflows (Presentation 7.1 uses the same investment research example). The open question at the 2026-09-13 call was the framing and the scope.

## Decision

The AI Investment Committee framing from Guna's proposal is the design: Bull and Bear analysts arguing from a shared evidence pool, on top of the assignment's planner, tools, evaluator, and memory. Scope rule for v1: simple is best, enough to learn, not a product.

v1 keeps two things that are not negotiable: every Bull and Bear claim carries a pointer to the evidence it came from, and the evaluator checks supported vs unsupported claims.

Stretch goals are documented but not promised: NLI-based claim checking, RAG over EDGAR filings, cross-model evaluation.

## Consequences

Scope discipline: features outside the v1 flow in docs/ARCHITECTURE.md need a superseding ADR before they get built. Stretch items appear in the proposal and README as documented possibilities, not commitments. The rubric map (docs/RUBRIC_MAP.md) is written against the v1 flow only.
