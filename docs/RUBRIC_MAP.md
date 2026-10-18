# Rubric map

**Overview:** one row per graded item from the Module 7 rubric (355 pts: Workflow Patterns 120, Agent Functions 120, Code 115). Each row says where the code lives and which section of the final notebook shows it.

| Graded item | Where it lives in src/ | Where the final notebook shows it | Status |
|-------------|------------------------|-----------------------------------|--------|
| Agent Function: plans its research steps | `agents/planner.py` | Section 2.1, and section 6 for planning from memory | done |
| Agent Function: uses tools dynamically | `tools/earnings.py`, `tools/news.py`, `tools/market.py` | Sections 2.2 to 2.4 | done |
| Agent Function: self-reflects on output quality | `agents/evaluator.py` | Section 5 (the evaluator and the self-reflection score) | done |
| Agent Function: learns across runs (memory) | `storage.py` (`save_memory_note`, `load_latest_note`), `workflows/runner.py` | Section 6 | done |
| Workflow Pattern: prompt chaining (ingest -> preprocess -> classify -> gate -> extract -> summarize) | `workflows/chaining.py` | Section 3 | done |
| Workflow Pattern: routing (earnings / news / market specialists) | `workflows/routing.py` | Section 2.2 | done |
| Workflow Pattern: evaluator-optimizer (generate -> evaluate -> refine) | `workflows/evaluator_optimizer.py` | Section 5, measured in section 7 | done |
| Code: readable notebook (PDF preferred, HTML acceptable) with GitHub link and comments on Agent Design and Workflows; Agent Functions and Capabilities; Evaluation and Iteration | whole package | `notebooks/final/AAI520_Group7_Final_Full.ipynb` and its PDF | done |
