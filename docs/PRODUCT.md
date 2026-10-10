# Product brief

Updated 2026-10-10. This describes the full architecture target. A foundation source alpha now exists; [STATUS.md](STATUS.md) distinguishes implemented behavior from the remaining scope.

## Owner requirements

- Brand: **Remember, Dammit.** Repository slug: `remember-dammit`.
- English public-facing materials.
- A useful personal second-brain vault with inspectable memory and source history.
- Model independence and multiple harnesses: Claude Code, Codex, Google Antigravity, Cursor, and an extensible path for others.
- Optional Jev/Laya-style assistance; the core must remain usable without it.

The previous proposal of a Claude/Codex-only project correction ledger was too narrow and is superseded. Corrections remain one behavior inside the broader vault.

## User and job

Someone who works and learns with several AI tools. Their knowledge includes personal preferences, people, source material, lessons, decisions, project work, and unfinished threads.

“Let me build one useful memory that I own, use it from the tool I choose, and understand what it remembers.”

## Product pillars

| Pillar | Required outcome |
| --- | --- |
| One coherent vault | Personal, shared, project, and session context have explicit boundaries and links. |
| Readable knowledge | Markdown survives without a model service, proprietary app, or live database. |
| Useful retrieval | Source-backed passages match the task, fit a stated budget, and explain their inclusion. |
| Durable learning | Corrections, rejected proposals, unresolved branches, and lessons have a lifecycle. |
| Interoperability | Different harnesses and models operate on the same IDs, revisions, and rules. |
| Safe maintenance | Parallel work, external edits, recovery, migrations, and optional synchronization have explicit contracts. |

## Core experience

1. Create a new vault or preview adoption of an existing Markdown/Obsidian vault without moving or rewriting it.
2. Choose which personal preferences and knowledge may be shared with a project; leave unrelated material out.
3. Capture selected material in an inbox with its origin, then turn useful material into linked, scoped notes.
4. Ask for relevant context from any attached harness. Receive passages, provenance, current status, and omissions.
5. Save an outcome or correction through the same shared write contract.
6. Open another harness and continue from current knowledge and the appropriate session card.
7. Inspect or maintain the vault in an ordinary editor; surfaced conflicts and histories remain accessible.

There is no mandatory new provider account, embedding model, daemon, or cloud subscription in the base path. Existing agents still use their own subscriptions or providers. Optional advisor and semantic-retrieval adapters are separate, deliberate additions.

## Architecture boundaries

- [Vault storage and lifecycle](VAULT.md) are independent of any model or harness.
- [Harness adapters](HARNESSES.md) normalize capabilities, not differences in user permission.
- [Advisors](PROVIDERS.md) assess bounded eligible inputs; they cannot become authoritative writers.
- Source material and tool results are data, not new instructions or permission grants.
- Scope filtering prevents accidental mixing through our interfaces; it is not a filesystem sandbox against an agent already granted broad disk access.

## Delivery order

### A. Vault contract and engine

Build the readable format, adoption preview, stable IDs, personal/project/session scope, source references, revisions, corrections, conflicts, recovery, lexical passage search, and bounded context assembly. Provide CLI + JSON and the shared MCP contract. Test with a synthetic vault and concurrent protocol clients.

### B. Four-harness integration gate

Validate explicit save, recall, correction, history, scope isolation, and fresh-session continuation in **all four named harnesses** against the same vault. Native hooks are separate capability levels; an unverified hook cannot be advertised as automatic support. Work may be sequenced one adapter at a time, but the first broad multi-harness release requires all four explicit workflows to pass.

### C. Assisted quality and convenience

Add advisor contracts, initially shadow evaluation; a Jev connector and separately installed local Laya connector only after protocol and egress tests. Add evaluated optional semantic retrieval and native lifecycle automation per surface. Advisor-disabled behavior remains the reference baseline.

### D. Maintenance and broader distribution

Add a vault inspector UI, evaluated synchronization workflows, further harness adapters, importers, and quality-of-life automation. Versioned storage and conflict semantics must exist before enabling cross-machine synchronization.

No live synchronization service or semantic merge is implied by portable files. Never copy a live SQLite database between machines.

## Acceptance families

1. Same-source retrieval, no-result abstention, multilingual alias/paraphrase cases, passage-level citations, and full-output context budgets.
2. Personal knowledge explicitly shared to a project; unrelated personal and project data excluded from results, graph expansion, previews, and provider calls.
3. Correction recalled through both old and new terms; superseded material remains history; competing descendants remain unresolved.
4. Parallel sessions with isolated cards; expected-base conflicts; duplicate retries; interrupted operations and exact recovery.
5. External Markdown edits, renamed/duplicated IDs, malformed metadata, case/Unicode path collisions, and adoption without data loss.
6. Rebuild local indexes from portable committed content and history without inventing or losing decisions.
7. Four real harnesses perform the same semantic workflow; record versions and explicit versus automatic behavior separately.
8. Advisor off means no provider activity; shadow cannot change results; timeout/malformed responses preserve the local baseline; changed sources invalidate stale advice.
9. Migration and restore are recoverable; uncommitted external edits are preserved; cross-device forks are surfaced before merge.

The implementation must turn these families into test fixtures and failure-injection cases. This is not a passing test report.

## Success evidence

Measure whether outside users can adopt a small vault, recall a real source, correct it, switch harnesses, and voluntarily use it again. Record failed lookups, repeated explanations, irrelevant context, conflicts, and setup friction. Stars are an interest signal, not a guaranteed outcome.
