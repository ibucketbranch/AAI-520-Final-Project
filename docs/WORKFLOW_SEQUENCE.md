# Workflow sequence and ownership

This diagram shows the sequence of one research run, the handoffs between
team members, and the separate evaluation performed across runs.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Planner as Planner and router<br/>Owner: Guna
    participant Gatherers as Market, earnings, and news fetchers<br/>Owner: Guna
    participant NewsChain as News processing chain<br/>Owner: Mina
    participant Store as Evidence pool and SQLite<br/>Owner: Guna
    participant Analysts as Bull and Bear analysts<br/>Owner: Michael
    participant Evaluator as Claim evaluator and revision loop<br/>Owner: Michael
    participant Notebook as Memo and final notebook<br/>Owner: Michael
    participant Harness as Evaluation harness and charts<br/>Owner: Mina

    User->>Planner: Submit stock symbol
    Planner->>Store: Load latest memory note for symbol
    Store-->>Planner: Return note or no prior note
    Planner->>Planner: Create research plan

    par Market and earnings path
        Planner->>Gatherers: Request market and earnings data
        Gatherers->>Gatherers: Fetch or load saved data
        Gatherers->>Store: Save market and earnings Evidence
    and News path
        Planner->>Gatherers: Request company news
        Gatherers->>NewsChain: Pass raw or saved articles
        NewsChain->>NewsChain: Ingest and preprocess
        NewsChain->>NewsChain: Classify, extract, and summarize
        NewsChain->>Store: Save news Evidence
    end

    Store-->>Analysts: Return combined evidence pool
    par Bull case
        Analysts->>Analysts: Draft evidence-linked Bull claims
    and Bear case
        Analysts->>Analysts: Draft evidence-linked Bear claims
    end
    Analysts->>Evaluator: Send claims and supporting evidence

    loop Until accepted or revision limit reached
        Evaluator->>Evaluator: Check each claim against its evidence
        alt Claim is unsupported
            Evaluator-->>Analysts: Return claim with a reason
            Analysts-->>Evaluator: Submit revised claim
        else Claim is supported
            Evaluator->>Store: Save reviewed claim
        end
    end

    Evaluator->>Evaluator: Record confidence and open gaps
    Evaluator->>Store: Save memory-note content
    Evaluator->>Notebook: Send accepted claims and sources
    Notebook->>Store: Save final memo and finish the run
    Notebook-->>User: Present memo with evidence

    Note over Harness,Evaluator: The same ticker is evaluated with the review loop disabled and enabled.
    Harness->>Store: Load comparable runs and their claims
    Store-->>Harness: Return without-review and with-review results
    Harness->>Harness: Count supported and unsupported claims
    Harness->>Harness: Compare results and create charts
    Harness->>Notebook: Add evaluation results to final notebook

    Note over Store,Planner: On the next run, the planner reads the saved memory note.
```

## Dependency summary

1. The shared models and SQLite storage contract enable all three work lanes.
2. Mina can develop the news chain from saved articles without waiting for live
   news fetching.
3. Michael can develop the analysts and evaluator from saved Evidence without
   waiting for the live gatherers.
4. The walking skeleton requires all three lanes to meet at the evidence pool.
5. Mina can build the evaluation harness structure early, but the final
   comparison depends on Michael's review loop producing both reviewed and
   unreviewed results.
6. Michael creates the memory-note content; Guna's storage module persists it,
   and Guna's planner reads it on the next run.
