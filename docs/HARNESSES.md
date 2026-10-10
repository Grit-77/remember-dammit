# Harness contract

Design and official-documentation research, 2026-10-10. The shared CLI/MCP server, four configuration proposals and an explicit-memory skill are implemented in the source alpha. **Native-client acceptance and automatic hooks remain unimplemented or unverified.** SDK subprocess checks are described in [STATUS.md](STATUS.md).

## One core, thin adapters

The engine understands vault IDs, project scope, sources, revisions, operations and budgets. It does not require an Anthropic, OpenAI, Google, or other model identifier to store or retrieve knowledge. Model/provider labels may be recorded as provenance without affecting format compatibility.

CLI JSON and MCP expose the same semantic operations: inspect/search, propose/commit, correct, context, history, and reconciliation. MCP is a transport for tools, not a promise that an agent will call them.

Every write supplies an operation ID, actor/session identity, explicit scope, payload, and expected base revision(s). Identity alone grants no write authority. Errors such as conflict, source-changed, scope-denied, recovery-required, and budget-too-small must remain machine-readable.

An adapter declares separately:

- Explicit retrieval and writes.
- Session identity and bounded continuation capture.
- Automatic context delivery at supported lifecycle events.
- Compaction/resume behavior.
- Native permission/trust requirements and transport availability.

Start with local stdio MCP and explicit CLI/file fallback where supported. A future remote MCP server needs a separately designed authorization and deployment path; local scope checks are not remote authentication.

## Initial targets

| Harness | Documented surfaces | Adapter boundary and fallback |
| --- | --- | --- |
| Claude Code | MCP, skills, CLAUDE.md/rules, lifecycle hooks | Explicit skill + MCP/CLI is the baseline. Instruction discovery and event availability depend on installed version; preserve existing instructions. |
| Codex | MCP, skills, AGENTS.md, lifecycle hooks | Explicit skill + MCP/CLI. Bootstrap hooks may run before MCP is ready; native hook trust must be completed through the client. |
| Cursor | MCP, skills, AGENTS.md/rules, lifecycle hooks | Explicit skill + MCP/CLI. Session-start is fire-and-forget; do not claim it blocks the first request until memory loads. IDE, CLI and cloud differ. |
| Google Antigravity | MCP, skills, rules, invocation/tool/stop hooks | Explicit skill + MCP/CLI. PreInvocation is per model invocation, so context delivery needs deduplication and a budget; it is not a generic SessionStart alias. |
| Other harnesses | Capability-dependent | Connect through the same protocol using MCP, shell tools or explicitly read context files. Record the actual supported subset; do not infer hook parity. |

These rows are integration targets, not release badges. Other adapters must not introduce their own canonical store.

## Installation behavior

Preview changes, merge only our own managed configuration entries, preserve custom rules and skills, and keep uninstall reversible. Do not overwrite an existing AGENTS.md/CLAUDE.md or change native tool permissions. Use a shared source for skill guidance with small generated wrappers when needed.

Reading an instruction file is guidance rather than enforcement. Tests must establish what the installed client actually loaded. Unknown hook versions disable that automatic path with an explicit fallback, rather than guessing payload schemas.

Hook handlers perform bounded deterministic synchronization or context retrieval. They do not silently start a second model, infer reliable memories from every transcript, or treat a Stop event as universally equivalent to application exit.

## Acceptance matrix required before claims

For each client/surface/platform combination record version, adapter version, transport, native trust state, and results for: attach, explicit save, fresh-session recall, correction, predecessor-term recall, project isolation, session isolation, history, uninstall and error fallback.

Then separately record start/resume/compaction/stop automation and duplicate-event handling. A local event simulator proves the adapter handler only; a real-client run is required for an automatic-context claim.

All four named clients must pass the explicit baseline before the first broad multi-harness release. Model changes should not alter vault format; capture any model-specific instruction-following limitations honestly.

## Official sources inspected

- Claude Code: [MCP](https://code.claude.com/docs/en/mcp), [skills](https://code.claude.com/docs/en/skills), [memory/instructions](https://code.claude.com/docs/en/memory), [hooks](https://code.claude.com/docs/en/hooks).
- Codex: [MCP](https://developers.openai.com/codex/mcp/), [skills](https://developers.openai.com/codex/skills/), [AGENTS.md](https://developers.openai.com/codex/guides/agents-md/), [hooks](https://developers.openai.com/codex/hooks/).
- Cursor: [MCP](https://cursor.com/docs/mcp), [skills](https://cursor.com/docs/skills), [rules](https://cursor.com/docs/rules), [hooks](https://cursor.com/docs/hooks).
- Antigravity: [MCP](https://antigravity.google/docs/mcp), [skills](https://antigravity.google/docs/skills), [rules](https://antigravity.google/docs/rules), [hooks](https://antigravity.google/docs/hooks).

Official documentation availability does not establish compatibility with the user's installed versions. Recheck during implementation.
