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
deliverable, due Sep 22. `DATABASE_URL` is not used and has been removed from
the configuration example. A hosted backend would need a separate implementation.
The gitignore carries the database file patterns.

## Committee handoff

The committee stays separate from `run_research`. The gathering run owns the
evidence. Both committee runs point to it through nullable `Run.parent_run_id`.
Each committee run has its own `with_review` flag, claims, model calls, and memo.
`open_db` adds the parent column to older databases without deleting their data.

Michael's committee code should load evidence using the parent ID, but assign
claims and model calls to the committee run ID. Keep the original evidence IDs
on claims; do not copy evidence rows just to change their run ID.

For Mina's comparison, both variants should start from the same evidence and
initial Bull/Bear draft. Only one variant goes through review. Generating two
fresh drafts would introduce another source of variation. Evaluation notes
should not be saved into normal planner memory; the harness can keep those
notes in its results until the team adds an explicit experiment marker.

The runner now reads the latest note for the ticker before planning. A failed
memory read is reported separately from a failed save. Until the news chain is
connected, a requested news step that returns no shared Evidence has a snapshot
warning. Raw articles are still shown, but are not stored as evidence.
