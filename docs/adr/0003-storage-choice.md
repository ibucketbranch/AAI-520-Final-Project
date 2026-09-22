# ADR-0003: Where shared state lives

Status: Accepted 2026-09-14

## Context

Two people need to share the evidence pool, run transcripts, and cross-run memory notes. Flat files in the repo are simplest but weakest for two people sharing state across machines, and data files are gitignored by policy. A hosted Postgres gives both of us (and a re-run of the final notebook) the same state.

## Options

1. Supabase Postgres: Michael has a free project slot; managed dashboard; Python access via connection string or client library.
2. Neon Postgres: Guna has used it; serverless Postgres with branching; free tier.
3. Flat files: no accounts, no network, works offline; weakest for two people sharing state, and every clone starts empty.

## Decision

SQLite. One local file the notebook builds on its first run from the committed
sample fixtures under `tests/fixtures/` (where the news and evidence samples
both live). Guna owns the schema and `storage.py`, the
single module that creates and touches the database; every other component
goes through that module. Database files (`*.db`, `*.sqlite`, `*.sqlite3`,
plus SQLite's `-shm` and `-wal` sidecars) are never committed.

The hosted options lost on reproducibility: Supabase and Neon both require an
account, credentials, and network access from anyone re-running the notebook,
including the grader. SQLite ships with Python and starts from the committed
fixtures with no setup.

## Consequences

`storage.py` and the shared record shapes in `models.py` are the contracts-first
deliverable, due Sep 22. `DATABASE_URL` stays in .env.example so a hosted
backend remains a connection-string change if collaboration ever demands it.
The gitignore carries the database file patterns.
