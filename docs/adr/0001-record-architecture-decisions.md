# ADR-0001: Record architecture decisions

Status: Accepted 2026-09-13

## Context

Two people building a graded system in six weeks need decisions written down where the code lives, not scattered across Slack threads and call transcripts. Michael Nygard's architecture decision record format is the smallest structure that captures a decision and why it was made.

## Decision

Any change to architecture, a dependency, or the work split gets an ADR in this directory. ADRs are numbered sequentially (0001, 0002, ...). Each has four sections: Status, Context, Decision, Consequences. An accepted ADR is never edited; a later ADR supersedes it and both note the link. The PR that implements a decision links its ADR.

## Consequences

Small writing cost per decision. In exchange, the proposal, the Status Update Form, and the final notebook's design commentary can all be assembled from these files, and neither of us has to reconstruct why a choice was made five weeks after the call where we made it.
