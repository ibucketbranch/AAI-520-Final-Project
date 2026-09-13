# Security

**Overview:** this is a two-person course project. Keys live in `.env` (gitignored) and are read only through `src/investment_committee/config.py`. Nothing reads a key any other way, and gitleaks scans every commit and the full history in CI.

**If a key leaks (committed, pasted in an issue, shared in Slack):**

1. Rotate the key at the provider first. A leaked key is dead the moment it leaks; rotation is the only fix.
2. Open an issue titled `[bug] key rotation` saying which key and where it leaked. Never paste the key material itself into the issue.
3. Rewriting git history to remove the leaked value happens only with both team members present, per CONTRIBUTING.md.
