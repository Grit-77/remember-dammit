# Remember, Dammit.

**I already told you.**

Local, source-linked memory shared by your AI agents.

> **Source alpha · 0.1.0a3.** A working local engine, CLI and stdio MCP server. Workspace setup is provided for Claude Code, Codex, Cursor and Antigravity. Their actual native-client acceptance is still pending; no automatic hooks are installed.

A new session should not mean explaining the same decision again. Save what matters, correct it when it changes, and inspect the history behind the current answer.

The vault format does not depend on a model provider. The core makes no model calls, needs no API key and starts no background service. Optional advisor calls require a separate explicit command and configuration. Your AI client continues to use its normal subscription or provider.

## Install with your agent

Give your agent this repository URL and say:

> Install https://github.com/Grit-77/remember-dammit by following its docs/AGENT-SETUP.md. Preserve my existing settings. After setup, ask whether I want no advisor, Jev, or Laya and explain what is available. Then use the remember-dammit skill: ask me a few short questions, save my answers as source notes, create a small task with me, and read it back from the vault.

The [agent setup guide](docs/AGENT-SETUP.md) covers the environment, a separate memory vault, workspace configuration, native client approval and first recall. Setup previews changes before applying them and preserves other settings. It installs a shared skill for a short first-use interview and verified readback.

**Jev and Laya are optional.** The owner CLI supports explicit shadow assessment: preview eligible requests, then deliberately ask hosted Jev or a local Laya server for relevance advice. Advice stays separate from recall and cannot write memory. Selecting an advisor during setup does not activate it. See the [provider setup guide](docs/PROVIDERS.md); local memory works without either.

## Try the actual engine

From this checkout, with Python 3.11+:

```powershell
git clone https://github.com/Grit-77/remember-dammit.git
cd remember-dammit
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[mcp]"
.venv/Scripts/python.exe examples/demo.py --vault .local/demo-vault
```

On macOS/Linux, substitute `.venv/bin/python` for `.venv/Scripts/python.exe`. The demo refuses an existing destination. It creates synthetic source notes, corrects SendGrid to Postmark, reopens the real vault, recalls the current decision using the old provider's name, and checks isolation from another project. It calls no AI model and does not simulate native-client acceptance.

See [installation and client configuration](docs/INSTALL.md) for explicit Windows commands. Nothing is published to PyPI yet; install from this checkout rather than an unrelated package-index name.

## What works in this alpha

- **Readable Markdown with immutable history.** Source-linked notes, decisions, preferences and session records share stable IDs.
- **Explicit scope.** Personal, shared and project knowledge are distinct. A personal note reaches a project only through a specific grant.
- **Corrections that preserve history.** Expected revisions prevent silent competing updates; former terminology can find the current decision.
- **Bounded recall.** Lexical passages, aliases, source citations, evidence labels, conflict bundles and omission notices fit a declared UTF-8 byte budget.
- **Participating writers coordinate.** Cross-process locking, idempotent operation IDs, atomic commit markers and a committed-head checkpoint protect tested write/retry paths.
- **Inspectable failures.** Doctor reports changed/missing committed content, orphan payloads and revoked-source dependencies.
- **Local MCP and CLI.** The server is bound to one project or personal selection. It cannot grant itself wider access.
- **Workspace setup.** Preview or apply the MCP entry and packaged skill for four harnesses, preserving unrelated settings and backing up changed files. Read-only configuration proposals remain available.
- **Markdown import.** Preview an existing notes folder, then import selected eligible Markdown as source records. Originals stay untouched; repeat imports reuse IDs and changed files become corrections.
- **Installation checks.** Inspect the chosen configuration, skill, Python runtime and vault with `setup-check`; native client approval is still separate.
- **Optional shadow assessment.** Use Jev or loopback Laya through the owner CLI with explicit configuration, egress checks and unchanged baseline recall.
- **Browsable snapshots.** Export a selected scope into a new Markdown folder with a Home page, source links and optional history. Exported edits do not update live memory.

The optional on-disk SQLite projection is disposable. Current search validates source records and builds its scoped FTS index in memory; large-vault performance has not been benchmarked.

## One vault, many clients

```text
Claude Code · Codex · Cursor · Antigravity · other MCP/CLI clients
                              ↓
                     one shared vault core
                              ↓
           Markdown · sources · revisions · explicit scopes
```

Generated configurations have been exercised with an SDK stdio client. That establishes a server launch and protocol exchange, not that a particular IDE loaded the server or followed its skill. Explicit save/recall and automatic lifecycle integration are separate capabilities. The native four-client matrix remains open.

## Where this is going

A full personal second brain: preferences, inbox, original sources, connected knowledge, projects, independent session cards and reviewable history. Browse the [illustrative vault](examples/vault/Home.md) for the intended organization.

Native editor reconciliation, offline multi-machine synchronization, semantic embeddings, automatic hooks, and automatic or result-changing advisor modes are **not implemented yet**. The alpha initializes a separate empty vault and can import Markdown copies through a reviewed plan. It treats direct edits to committed revision payloads as integrity errors. Optional shadow adapters assess bounded candidates; live provider readiness and answer quality have not been established by the protocol tests.

## Read more

- [Implemented behavior and current limits](docs/STATUS.md)
- [Install and configure clients](docs/INSTALL.md)
- [Product scope](docs/PRODUCT.md)
- [Vault architecture](docs/VAULT.md)
- [Harness contract](docs/HARNESSES.md)
- [Optional Jev/Laya design](docs/PROVIDERS.md)
- [Claim evidence and verification commands](FACTS.md)

Run the development checks:

```sh
python -m unittest discover -s tests -v
```

[Apache-2.0 licensed](LICENSE). No perfect-recall, universal compatibility, cost-saving or adoption claim is made.
