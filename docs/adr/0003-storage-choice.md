# ADR-0003: Where shared state lives

Status: Proposed

## Context

Two people need to share the evidence pool, run transcripts, and cross-run memory notes. Flat files in the repo are simplest but weakest for two people sharing state across machines, and data files are gitignored by policy. A hosted Postgres gives both of us (and a re-run of the final notebook) the same state.

## Options

1. Supabase Postgres: Michael has a free project slot; managed dashboard; Python access via connection string or client library.
2. Neon Postgres: Guna has used it; serverless Postgres with branching; free tier.
3. Flat files: no accounts, no network, works offline; weakest for two people sharing state, and every clone starts empty.

## Decision

Pending the Tuesday 2026-09-15 call.

## Consequences

Pending. `DATABASE_URL` in .env.example and `memory/store.py` are written so the backend is a connection-string change.
