# Remember, Dammit.

**I already told you.**

One vault. Different agents. Your memory.

> **Design stage:** no installable release, working adapter, or measured retrieval result exists yet. This repository contains the proposed architecture, an illustrative vault, and acceptance plans.

You have preferences, projects, sources, decisions, and things you learned the hard way. They should remain useful when you open a new session, change your model, or switch tools.

Remember, Dammit. is being designed as a local, model-independent second-brain vault. **Claude Code, Codex, Google Antigravity, and Cursor are first-class integration targets.** Additional harnesses should connect through the same versioned protocol, without creating another memory store.

## A vault you can live in

- **You:** preferences and working principles you deliberately share with your agents.
- **Sources:** the notes, documents, and selected conversation excerpts behind a claim.
- **Knowledge:** linked concepts, people, lessons, and decisions with traceable sources.
- **Projects:** goals, project-specific context, open questions, and current work.
- **Sessions:** separate continuation records so parallel agents do not overwrite one shared last-session file.
- **History:** corrections and unresolved branches that stay inspectable.

The layout is a starter, not a mandatory reorganization of your existing Obsidian vault. Open the [illustrative vault](examples/vault/Home.md) to see the intended experience.

## Remember what matters

The proposed flow is:

**Capture → connect to sources → organize → retrieve relevant context → correct and learn.**

The engine assembles a small context for the current task instead of injecting the whole vault. It should explain why a memory was included, where it came from, and whether its source needs review. Corrected decisions stay in history without being presented as current instructions.

An agent can contribute within the user's configured capture policy. The engine does not pretend that every conversation automatically becomes reliable knowledge.

## Harness-independent by design

One core serves a CLI, structured JSON, and an MCP interface. Thin adapters translate each client's skills, rules, and lifecycle events into that common contract.

MCP availability is not proof of automatic recall. Explicit read/write workflows and native lifecycle automation will be tested and reported separately for each client and surface. See the [harness contract](docs/HARNESSES.md).

## Optional advisors

Jev and Laya are planned optional advisor integrations, following the role separation studied in Avenox Beyin. They are **not the vault, the default search engine, or mandatory model providers**.

The local core must work with advisors disabled. Advisor results can help assess candidates or source support, but cannot authorize writes or expand access. Provider setup, transmitted content, limits, and fallback behavior must remain explicit. See the [provider contract](docs/PROVIDERS.md).

## Read the design

- [Product scope and delivery gates](docs/PRODUCT.md)
- [Vault architecture and data lifecycle](docs/VAULT.md)
- [Harnesses and future adapters](docs/HARNESSES.md)
- [Optional Jev/Laya advisors](docs/PROVIDERS.md)
- [Multi-harness demo plan](docs/DEMO.md)
- [Research and source links](docs/RESEARCH.md)
- [Approved decisions and proposals](docs/DECISIONS.md)

Inspired by [Avenox Beyin](https://github.com/avenoxai/avenoxbeyin). No upstream implementation has been copied into this project. No performance, adoption, universal compatibility, or perfect-recall claim is made.
