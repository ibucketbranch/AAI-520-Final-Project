# ADR-0005: Select the planner provider in the UI

Status: Accepted 2026-09-26

## Context

The real planner needs a language model, but the project should still run for a grader who does not have an API key. The team may also test other model providers later.

## Decision

The runner accepts a planner provider. The Streamlit page sends this value with the stock symbol and selects OpenAI by default. OpenAI and the existing rule-based planner both return the same `ResearchPlan`, so routing and gatherers do not change. If the OpenAI key is missing or the request fails, the runner uses the rule-based plan and shows that fallback in the UI.

Only providers that are implemented appear in the menu. Anthropic and Google can be added later by writing another planner function that returns the same plan shape.

Successful planner calls are saved in SQLite with the run, evidence, token counts, and latency.

## Consequences

The local interface can use a real model now and still works offline. Adding another provider does not require changes to the rest of the research workflow. OpenAI becomes a project dependency, and a live OpenAI run may use paid API credits.
