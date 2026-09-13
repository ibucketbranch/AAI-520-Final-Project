# ADR-0002: The AI Investment Committee is the project

Status: Accepted 2026-09-13

## Context

Two-person team (Michael Valderrama, Guna Pasupathy), six weeks to the final notebook, and a rubric that grades four agent functions, three workflow patterns, and code quality. Two candidate projects were on the table at the 2026-09-13 planning call: Guna's AI Investment Committee (multi-agent stock research) and Michael's agent-economics idea (AEQ). Both agreed AEQ is too large to finish in six weeks with two people.

## Decision

Guna's AI Investment Committee is the project. Scope rule for v1: simple is best, enough to learn, not a product.

v1 keeps two things that are not negotiable: every Bull and Bear claim carries a pointer to the evidence it came from, and the evaluator checks supported vs unsupported claims.

Stretch goals are documented but not promised: NLI-based claim checking, RAG over EDGAR filings, cross-model evaluation. Michael's AEQ idea is out of scope for this course.

## Consequences

Scope discipline: features outside the v1 flow in docs/ARCHITECTURE.md need a superseding ADR before they get built. Stretch items appear in the proposal and README as documented possibilities, not commitments. The rubric map (docs/RUBRIC_MAP.md) is written against the v1 flow only.
