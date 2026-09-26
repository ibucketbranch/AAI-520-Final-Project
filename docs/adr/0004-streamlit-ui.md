# ADR-0004: Use Streamlit for the optional local UI

Status: Accepted 2026-09-26

## Context

The proposal lists a small user interface as a stretch goal. The interface only needs to accept a stock symbol and display the existing runner output. It should run locally, require no separate frontend project, and remain easy to remove if the committed workflow needs more time.

## Decision

Use one Streamlit page in `app.py`. It calls the same `run_research` function used by Python code and does not contain research logic. The first version displays the planner, earnings evidence, news articles, and market evidence. Analyst, evaluator, and memo output will appear only after those stages are connected to the runner.

## Consequences

The team gets a usable local interface with little UI code, but Streamlit becomes a project dependency. The page is a stretch feature and does not replace the final notebook. Live runs still depend on yfinance availability.
