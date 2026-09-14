# Contributing

**Overview:** how two people work in this repo without colliding. Everything goes through a pull request; `make check` runs the same checks locally that CI runs on GitHub.

## 1. Branch flow

- `main` is protected. Branch from `main` as `<initials>/<type>-<short-slug>`, for example `mv/feat-planner` or `gp/feat-news-tool`.
- One issue, one branch, one PR. Keep PRs under about 400 changed lines; split otherwise.
- Squash merge only; the PR title becomes the commit message on `main`; delete the branch after merge.

## 2. Reviews

- One approval from the other person, required by branch protection.
- Review within 24 hours on weekdays; say so in Slack if you cannot.
- Approve means "I ran it or read it well enough to own it."

## 3. Ownership

- One owner per area: `agents/`, `tools/`, `workflows/`, `memory/`, `evaluation/`, `notebooks/final`.
- Touch another owner's area only through a PR they review.
- The owner map lives in docs/ARCHITECTURE.md and .github/CODEOWNERS.

## 4. Notebooks

- Logic lives in `src/`; notebooks import it (`pip install -e .`).
- Dev notebooks go under `notebooks/dev/` named `<initials>_<topic>.ipynb`. Outputs are stripped on commit, and dev notebooks are never merged into each other.
- The single final notebook under `notebooks/final/` is assembled in the last week from the package and is the only notebook that keeps outputs (Kahila, Sep 11: one combined notebook; HTML is acceptable; comments stay in the notebook even with a report).

## 5. Local = CI

- `make check` runs exactly what CI runs. Do not open a PR red.
- Tests must not call the internet; mock every tool.

## 6. Secrets and data

- Keys only in `.env`, never committed; nothing reads a key outside `src/investment_committee/config.py`.
- Data only under `data/` (gitignored).
- If a key leaks: rotate it first, then open an issue, then rewrite history only with both people present. See SECURITY.md.

## 7. Decisions

- Anything that changes architecture, a dependency, or the split gets an ADR in `docs/adr/` (copy 0001 as the template).
- The PR that implements a decision links its ADR.

## 8. Commit and PR titles

- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `ci:`). The pr-title check enforces this on every PR.
- Plain ASCII in docs and notebook markdown (Turnitin and Canvas paste hygiene, same rule as the course repo).

## 9. AI tools

- Use them, disclose them in the PR description, and be able to explain every line you merge.
- docs/AI_DISCLOSURE.md is the standard and the template for the notebook's disclosure section.

## 10. Cadence

- Standing call Tuesdays 4:30 PM PT. Slack channel `#group7-mina_-guna-_michael`, plus text for anything urgent.
- Milestones: Team Project Status Update Form Mon Sep 28; final notebook Mon Oct 19, 11:59 PM PT, no extensions, three Canvas submission attempts.

Guardrails verified 2026-09-14; see the repo setup report.

<!-- guardrail verification probe; this PR is closed unmerged -->
