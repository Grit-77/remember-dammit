# Decisions

## Owner-approved requirements — 2026-10-10

- Name: **Remember, Dammit.**
- Repository slug: `remember-dammit`.
- Public-facing language: English.
- Public open-source direction inspired by Avenox Beyin.
- Memorable direct naming with personality, as in Done is a claim.
- The product must be model-independent and work across many harnesses, explicitly including Claude Code, Codex, Antigravity, and Cursor.
- The vault itself is central: a personal second brain, not merely a two-client project ledger.
- Jev/Laya may be optional integrations. Their use must not be a prerequisite for the vault.

No public remote exists. A local runnable 0.1.0a1 source alpha now implements the foundation; see [STATUS.md](STATUS.md) for its tested scope and remaining work.

## Superseded proposal

The initial brief limited the product to a project-local correction ledger targeting only Claude Code and Codex. The owner explicitly expanded this scope. Its correction/history acceptance cases remain part of the full vault; its two-client and project-only boundaries no longer govern the design.

## Current design proposals

- Opening line: **I already told you.**
- Organization: user context, inbox, sources, connected knowledge, projects, separate session cards, and history.
- Shared model-neutral engine with CLI/JSON/MCP and capability-specific adapters.
- Human-readable Markdown plus portable revision/provenance metadata; machine-local indexes are disposable.
- Local lexical passage search as the mandatory baseline, with evaluated optional semantic retrieval.
- Advisors disabled by default; shadow evaluation before active effects. Laya initially shadow-only, consistent with the upstream evidence studied.
- Python as a core implementation candidate, not a frozen dependency or packaging contract.
- MIT selected for the original source alpha; retain upstream notices for any future substantial reuse. No upstream implementation has been copied.

## Open engineering choices

- Final storage schema and transaction protocol, validated against VAULT.md failure cases.
- Packaging/dependency choices for Markdown metadata, search, cross-platform locking, and MCP.
- Exact native automation per installed harness surface.
- Retrieval fixtures and evaluation thresholds, provider performance/cost observations, and supported synchronization paths.
- License and installation routes before implementation distribution.

Approved requirements are not evidence that proposed behavior is implemented or tested. No optional provider has been enabled or called by this design work.
