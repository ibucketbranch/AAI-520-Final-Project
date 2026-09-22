"""Shared record shapes for the investment committee.

Every component reads and writes the same five records, defined once here:
Run (one end-to-end research run), Evidence (one fact a gatherer found),
Claim (one statement from Bull or Bear and the evidence it points at),
MemoryNote (what a run learned for next time), and ModelCall (one logged
call to a language model). Nothing else in the package defines its own copy.

They are pydantic models so a bad record fails at the point it is built,
not three stages later. storage.py turns them into rows and back, so every
field name here is also a column name there.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# The three gatherers in docs/ARCHITECTURE.md, one label each.
Source = Literal["earnings", "news", "market"]

# Which analyst made a claim.
Side = Literal["bull", "bear"]


def new_id() -> str:
    """Return a short random id for a new record."""
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Run(BaseModel):
    """One end-to-end research run for a stock symbol.

    with_review is False for the "without the review loop" runs in the
    evaluation, so the two kinds can be told apart afterwards. memo and
    finished_at are filled in when the run completes.
    """

    run_id: str = Field(default_factory=new_id)
    symbol: str
    with_review: bool = True
    started_at: str = Field(default_factory=now_iso)
    finished_at: str | None = None
    memo: str | None = None


class Evidence(BaseModel):
    """One fact a gatherer found. The evidence pool is a list of these.

    reference says where the fact came from (a URL, or something like
    "yfinance:AAPL:income_stmt") so a reader can check it.
    """

    evidence_id: str = Field(default_factory=new_id)
    run_id: str
    symbol: str
    source: Source
    title: str
    content: str
    as_of: str
    reference: str


class Claim(BaseModel):
    """One statement from Bull or Bear, with pointers to its evidence.

    ADR-0002 rule: every claim carries at least one evidence pointer, so
    evidence_ids cannot be empty. The evaluator fills in supported and
    reason; a claim that was sent back and rewritten comes back with
    revision + 1.
    """

    claim_id: str = Field(default_factory=new_id)
    run_id: str
    side: Side
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    supported: bool | None = None
    reason: str | None = None
    revision: int = 0


class MemoryNote(BaseModel):
    """What one run learned, read by the planner at the start of the next.

    confidence is the drafting step's own estimate, 0 to 1, and open_gaps
    lists what it could not find out. Together they are the self-reflection
    record from the proposal.
    """

    note_id: str = Field(default_factory=new_id)
    run_id: str
    symbol: str
    confidence: float = Field(ge=0.0, le=1.0)
    open_gaps: list[str]
    lesson: str
    created_at: str = Field(default_factory=now_iso)


class ModelCall(BaseModel):
    """One logged call to a language model, for replay and cost accounting.

    stage names the caller (planner, bull, bear, evaluator). The token
    counts and latency are what the API reported; 0 when the stage is
    still a stub that made no real call.
    """

    call_id: str = Field(default_factory=new_id)
    run_id: str
    stage: str
    model: str
    prompt: str
    response: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    created_at: str = Field(default_factory=now_iso)
