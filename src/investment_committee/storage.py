"""The single door to the SQLite database (ADR-0003).

Every read and write in the project goes through this module; nothing else
opens a connection or touches a table. The database is one local file that
open_db() creates on first use, so a fresh clone needs no setup and no key,
and seed_from_json() fills it from committed sample data.

The layout is deliberately plain: one table per record shape in models.py,
one row per record, column names equal to field names, and the two list
fields (evidence_ids, open_gaps) stored as JSON text in a single column.
Tests open the database at ":memory:".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from investment_committee.models import Claim, Evidence, MemoryNote, ModelCall, Run

# Where the database lives by default. data/ is gitignored, so the file
# never ends up in a commit.
DEFAULT_DB_PATH = Path("data/committee.db")

# One CREATE TABLE per record shape, in the order a run writes them.
# IF NOT EXISTS makes open_db() safe to call every time.
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    with_review INTEGER NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    memo        TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    symbol      TEXT NOT NULL,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    reference   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id     TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    side         TEXT NOT NULL,
    text         TEXT NOT NULL,
    evidence_ids TEXT NOT NULL,
    supported    INTEGER,
    reason       TEXT,
    revision     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_notes (
    note_id    TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    symbol     TEXT NOT NULL,
    confidence REAL NOT NULL,
    open_gaps  TEXT NOT NULL,
    lesson     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    call_id           TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    stage             TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt            TEXT NOT NULL,
    response          TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    latency_ms        INTEGER NOT NULL,
    created_at        TEXT NOT NULL
);
"""


def open_db(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the file and the tables on first use.

    Args:
        path: The database file, or ":memory:" for a throwaway database.

    Returns:
        An open connection with foreign keys on and rows readable by name.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---- writes -----------------------------------------------------------------


def save_run(conn: sqlite3.Connection, run: Run) -> None:
    """Insert a new run. Save the run before anything that points at it."""
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, symbol, with_review, started_at, finished_at, memo)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run.run_id, run.symbol, run.with_review, run.started_at, run.finished_at, run.memo),
        )


def finish_run(conn: sqlite3.Connection, run_id: str, memo: str, finished_at: str) -> None:
    """Record the final memo and end time of a run."""
    with conn:
        conn.execute(
            "UPDATE runs SET memo = ?, finished_at = ? WHERE run_id = ?",
            (memo, finished_at, run_id),
        )


def save_evidence(conn: sqlite3.Connection, items: list[Evidence]) -> None:
    """Insert a batch of evidence items, all at once."""
    rows = [
        (e.evidence_id, e.run_id, e.symbol, e.source, e.title, e.content, e.as_of, e.reference)
        for e in items
    ]
    with conn:
        conn.executemany(
            "INSERT INTO evidence (evidence_id, run_id, symbol, source, title, content,"
            " as_of, reference) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def save_claim(conn: sqlite3.Connection, claim: Claim) -> None:
    """Insert a claim, or replace it if the same claim_id is already saved.

    Replacing is how the evaluator records its verdict: it sets supported
    and reason on the Claim and saves it again.
    """
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO claims (claim_id, run_id, side, text, evidence_ids,"
            " supported, reason, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim.claim_id,
                claim.run_id,
                claim.side,
                claim.text,
                json.dumps(claim.evidence_ids),
                claim.supported,
                claim.reason,
                claim.revision,
            ),
        )


def save_memory_note(conn: sqlite3.Connection, note: MemoryNote) -> None:
    """Insert the note a run leaves for the next one."""
    with conn:
        conn.execute(
            "INSERT INTO memory_notes (note_id, run_id, symbol, confidence, open_gaps,"
            " lesson, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                note.note_id,
                note.run_id,
                note.symbol,
                note.confidence,
                json.dumps(note.open_gaps),
                note.lesson,
                note.created_at,
            ),
        )


def save_model_call(conn: sqlite3.Connection, call: ModelCall) -> None:
    """Log one model call."""
    with conn:
        conn.execute(
            "INSERT INTO model_calls (call_id, run_id, stage, model, prompt, response,"
            " prompt_tokens, completion_tokens, latency_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call.call_id,
                call.run_id,
                call.stage,
                call.model,
                call.prompt,
                call.response,
                call.prompt_tokens,
                call.completion_tokens,
                call.latency_ms,
                call.created_at,
            ),
        )


# ---- reads ------------------------------------------------------------------


def _record(row: sqlite3.Row, json_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    """Turn a row into a dict, decoding the listed JSON text columns."""
    record = dict(row)
    for name in json_fields:
        record[name] = json.loads(record[name])
    return record


def load_run(conn: sqlite3.Connection, run_id: str) -> Run | None:
    """Return one run, or None if there is no run with that id."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return Run(**_record(row))


def load_evidence(conn: sqlite3.Connection, run_id: str) -> list[Evidence]:
    """Return the evidence pool of a run, in the order it was saved."""
    rows = conn.execute("SELECT * FROM evidence WHERE run_id = ? ORDER BY rowid", (run_id,))
    return [Evidence(**_record(row)) for row in rows]


def load_claims(conn: sqlite3.Connection, run_id: str) -> list[Claim]:
    """Return every claim of a run, in the order it was saved."""
    rows = conn.execute("SELECT * FROM claims WHERE run_id = ? ORDER BY rowid", (run_id,))
    return [Claim(**_record(row, ("evidence_ids",))) for row in rows]


def load_latest_note(conn: sqlite3.Connection, symbol: str) -> MemoryNote | None:
    """Return the newest memory note for a symbol, or None on the first run.

    This is what the planner reads before it plans.
    """
    row = conn.execute(
        "SELECT * FROM memory_notes WHERE symbol = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    return MemoryNote(**_record(row, ("open_gaps",)))


def load_model_calls(conn: sqlite3.Connection, run_id: str) -> list[ModelCall]:
    """Return every logged model call of a run, in the order it was made."""
    rows = conn.execute("SELECT * FROM model_calls WHERE run_id = ? ORDER BY rowid", (run_id,))
    return [ModelCall(**_record(row)) for row in rows]


# ---- first-run build --------------------------------------------------------


def seed_from_json(conn: sqlite3.Connection, path: str | Path) -> int:
    """Load a saved run and its evidence from a JSON file, once.

    The file holds {"run": {...}, "evidence": [...]} with the Run and
    Evidence fields. If the run is already in the database the file is
    skipped, so the notebook can call this on every start and only the
    first call does any work.

    Args:
        conn: An open connection from open_db().
        path: The JSON file of committed sample data.

    Returns:
        The number of evidence rows inserted; 0 if the run was already there.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    run = Run(**data["run"])
    if load_run(conn, run.run_id) is not None:
        return 0
    items = [Evidence(**item) for item in data["evidence"]]
    save_run(conn, run)
    save_evidence(conn, items)
    return len(items)
