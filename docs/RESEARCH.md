# Research and positioning

Research date: 2026-10-10. This is a documentation-level market scan, not a comparative runtime benchmark.

## What the existing tools already cover

| Project | Relevant overlap |
| --- | --- |
| [Avenox Beyin](https://github.com/avenoxai/avenoxbeyin) | Local Markdown memory, multiple agent clients, straightforward setup without a required API key for its memory engine. |
| [Basic Memory](https://github.com/basicmachines-co/basic-memory) | Shared human/AI Markdown knowledge, retrieval, and MCP integration. |
| [Claude-Mem](https://github.com/thedotmack/claude-mem) | Session capture, retrieval, and context carried into subsequent sessions. |
| [ThreadPort](https://github.com/Frankie-Xu/threadport) | Continuation previews, Git/workspace snapshots, drift checks, historical command applicability, and decision conflicts. |
| [Unlost](https://github.com/unfault/unlost) | Decision provenance, file/symbol recall, and Git-grounded context. |
| [Context Passport](https://github.com/macio-arruda/context-passport) | Portable operational context and destination-specific handoff packs. |

Repository documentation describes capabilities; it does not independently establish their quality or reliability. Features may change after this research date.

## Consequence for this project

Local storage, multiple clients, a graph view, and verified handoffs are not sufficient novelty claims. Remember, Dammit. should start by making one correction workflow easy to install, inspect, and reproduce.

The proposed advantage is the quality of that experience, not an assertion that no competing product can perform it. It must be tested with users. The owner subsequently clarified that the product must be a full personal vault usable across Claude Code, Codex, Antigravity, Cursor and other harnesses. The correction workflow is one validation case inside that broader scope.

The owner cited their existing [Done is a claim](https://github.com/Grit-77/done-is-a-claim) as a naming reference: a memorable statement about a recognizable problem. That is the intended relationship; this project is not a renamed copy of another memory tool.

## Naming evidence

On 2026-10-10, public GitHub repository-name API searches for `remember-dammit in:name` and `rememberdammit in:name` each returned `total_count: 0`.

This is a dated observation about public indexed repository search. It does not reserve a repository, package, domain, or trademark, or establish that private/unindexed repositories do not exist.

## Growth hypothesis

A memorable name can earn attention; a successful first use and a useful second session need to earn continued use. Begin with an English README, an actual short demonstration, a reproducible fixture, and clear installation instructions. Publish measured evidence only after the corresponding checks run.

No projected star count, adoption target presented as a forecast, or unmeasured speed/token claim forms part of the plan.

## Avenox vault and advisor source inspection

Observed upstream VERSION 3.9.0 at commit `d8167fb897086f8f6177870f7c92c8fa7c2a1314`, dated 2026-10-09. Source was read, not executed. No implementation has been copied into this repository.

- [Markdown format](https://github.com/avenoxai/avenoxbeyin/blob/d8167fb897086f8f6177870f7c92c8fa7c2a1314/docs/v3/MARKDOWN.md): Markdown authority, stable IDs, metadata, invalid-source and duplicate-ID handling.
- [Runtime](https://github.com/avenoxai/avenoxbeyin/blob/d8167fb897086f8f6177870f7c92c8fa7c2a1314/docs/v3/RUNTIME.md): local lexical/passaged retrieval, source eligibility, freshness checks, citations and budgets. No embedding dependency in the baseline.
- [Multiple machines](https://github.com/avenoxai/avenoxbeyin/blob/d8167fb897086f8f6177870f7c92c8fa7c2a1314/docs/v3/MULTI-MACHINE.md): portable notes/receipts, machine-local indexes, and conflict caveats. Local writer coordination is not a distributed merge protocol.
- [Jev/Laya](https://github.com/avenoxai/avenoxbeyin/blob/d8167fb897086f8f6177870f7c92c8fa7c2a1314/docs/v3/JEV.md): optional assessment, never implicit write approval; Laya restricted to shadow. These are advisors, not embedding engines.
- [Live clients](https://github.com/avenoxai/avenoxbeyin/blob/d8167fb897086f8f6177870f7c92c8fa7c2a1314/docs/v3/LIVE-CLIENTS.md): real-client evidence is distinct from hook simulation and explicit CLI behavior.

Upstream is MIT, copyright 2026 Avenox; substantial future reuse must retain the relevant notices. Its Jev client also includes third-party attribution. Licensing details must be reviewed for the specific files reused.

## Harness and editor evidence

Current official integration sources and their limits are recorded in [HARNESSES.md](HARNESSES.md). No installed client was exercised by this research.

[Obsidian properties](https://obsidian.md/help/properties) supports flat typed YAML and lists; nested metadata has editor limitations. [Obsidian Sync conflict documentation](https://obsidian.md/help/sync/troubleshoot) describes Markdown merging and conflict-file behavior. Therefore this design cannot assume external editors cooperate with application locks or that a sync service resolves semantic memory conflicts.
