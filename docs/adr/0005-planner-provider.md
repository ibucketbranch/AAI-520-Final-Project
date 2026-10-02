# ADR-0005: Select the planner provider in the UI

Status: Accepted 2026-09-26

## Context

The real planner needs a language model, but the project should still run for a grader who does not have an API key. The team may also test other model providers later.

## Decision

The runner accepts a planner provider. The Streamlit page sends this value with the stock symbol and selects OpenAI by default. OpenAI and the existing rule-based planner both return the same `ResearchPlan`, so routing and gatherers do not change. If the OpenAI key is missing or the request fails, the runner uses the rule-based plan and shows that fallback in the UI.

Only providers that are implemented appear in the menu. Anthropic and Google can be added later by writing another planner function that returns the same plan shape.

Successful planner calls are saved in SQLite with the run, evidence, token counts, and latency.

`OPENAI_TIMEOUT` sets the request timeout in seconds (default 30). Both planner
requests and model discovery use `Settings.openai_timeout()`. Michael's analyst
client should use this same method when its PR is connected. Provider errors
and invalid structured responses fall back to rules; programming errors are
not caught as provider failures.

The UI also queries the selected provider for model names. As of Sep 28, the menu keeps only the current general-purpose aliases: `gpt-6-luna`, `gpt-6-sol`, and `gpt-6-astra`. Each name must also appear in the account's API catalog. This short list hides older generations and dated duplicates; it can be updated when the team adopts another model family. The existing planner fallback still applies if a selected model rejects the request.

The selected model is passed through the runner to the planner. It overrides `OPENAI_MODEL` for that run. The UI caches the list for five minutes and offers a refresh button. If listing fails, it shows a current default with a warning. An older configured default is replaced by `gpt-6-luna` in the UI. Rule-based planning skips model discovery.

## Consequences

The local interface can use a real model now and still works offline. Adding another provider does not require changes to the rest of the research workflow. OpenAI becomes a project dependency, and a live OpenAI run may use paid API credits.
