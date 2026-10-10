# Decisions

## Owner-approved requirements — 2026-10-10

- Name: **Remember, Dammit.**
- Repository slug: `remember-dammit`.
- Public-facing language: English.
- Public open-source personal-memory vault.
- Memorable direct naming with personality.
- The product must be model-independent and work across many harnesses, explicitly including Claude Code, Codex, Antigravity, and Cursor.
- The vault itself is central: a personal second brain, not merely a two-client project ledger.
- Jev/Laya may be optional integrations. Their use must not be a prerequisite for the vault.

The owner authorized public publication on 2026-10-10. A runnable 0.1.0a1 source alpha implements the foundation; see [STATUS.md](STATUS.md) for its tested scope and remaining work.

## Superseded proposal

The initial brief limited the product to a project-local correction ledger targeting only Claude Code and Codex. The owner explicitly expanded this scope. Its correction/history acceptance cases remain part of the full vault; its two-client and project-only boundaries no longer govern the design.

## Current design proposals

- Opening line: **I already told you.**
- Organization: user context, inbox, sources, connected knowledge, projects, separate session cards, and history.
- Shared model-neutral engine with CLI/JSON/MCP and capability-specific adapters.
- Human-readable Markdown plus portable revision/provenance metadata; machine-local indexes are disposable.
- Local lexical passage search as the mandatory baseline, with evaluated optional semantic retrieval.
- Advisors disabled by default; shadow evaluation before active effects. Candidate providers require their own compatibility and quality checks.
- Python with PyYAML is the implemented core; the official MCP SDK is an optional extra. The current package contract is in pyproject.toml.
- Apache-2.0 selected by the owner for new development on 2026-10-10.

## Open engineering choices

- Final storage schema and transaction protocol, validated against VAULT.md failure cases.
- Further packaging routes and dependency changes beyond the current source installation.
- Exact native automation per installed harness surface.
- Retrieval fixtures and evaluation thresholds, provider performance/cost observations, and supported synchronization paths.
- Future packaged releases beyond the current Apache-2.0-licensed source alpha.

Approved requirements are not evidence that proposed behavior is implemented or tested. No optional provider has been enabled or called by this design work.
