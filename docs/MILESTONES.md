# Milestones

**Overview:** the team plans by dated Tuesday check-ins, not course modules. A
module is what the course teaches that week; a milestone is what runs by a
date. The module column exists as a cross-reference for the instructor.

| Tuesday | Course context | Milestone |
|---------|----------------|-----------|
| Sep 15 | Module 2 | Repo up with CI and branch rules, proposal agreed, owners named |
| Sep 22 | Module 3 | Data layer done, sample data committed, SQLite builds on first run, news chain runs on saved articles |
| Sep 29 | Module 4 | Walking skeleton end to end with stubs; Status Update Form submitted Sep 28 |
| Oct 6 | Module 5 | Real planner, real Bull and Bear, one model wired |
| Oct 13 | Module 6 | Review loop and memory note working; with/without measurement run |
| Oct 20 | After Module 7 | Final submitted Oct 19; peer eval and retro |

## Per-person, Sep 22

| Person | Deliverable |
|--------|-------------|
| Guna | models.py (shared record shapes) and storage.py (the only door to the database), sample market and earnings data committed |
| Mina | Take ownership of the news chain (v1 merged Sep 15): review it, add the gate after classify, wire it to the shared models |
| Michael | Bull, Bear, and evaluator stubs that read Evidence and emit Claims with evidence pointers |

## Per-person, Sep 29

| Person | Deliverable |
|--------|-------------|
| Guna | Planner and router stubs wired to the tools |
| Mina | Evaluation harness skeleton: run the same tickers with and without review, count supported vs unsupported |
| Michael | Walking skeleton assembled end to end; Status Update Form submitted Sep 28 |

Later weeks are set at the prior call.
