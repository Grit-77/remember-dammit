# Remember, Dammit.

**Stop explaining your project from scratch.**

One local memory vault for your AI agents. Save the decisions, preferences and
sources that matter. Ask for them again in a new session. When a decision changes,
keep the correction and the history behind it.

**[Get started with your agent →](#get-started)**

Source alpha · Python 3.11+ · [Apache-2.0](LICENSE)

![Remember, Dammit. — generated brand artwork.](docs/assets/remember-dammit-hero.jpg)

[See a real memory correction](#try-it-without-an-ai-client) · [Native client test report](docs/LIVE-ACCEPTANCE.md)

## Get started

Give your agent this message in the project where you want memory:

> Install https://github.com/Grit-77/remember-dammit by following docs/AGENT-SETUP.md. Preserve my settings. Help me save one useful fact and actually read it back. Then help me get started with the remember-dammit skill and ask whether I want no optional advisor, Jev, or Laya.

The [agent setup guide](docs/AGENT-SETUP.md) covers choosing a vault and scope,
previewing workspace changes, applying the configuration and completing the
client's native approvals. The agent helps with installation; the package does
not automatically install Python or change global client settings.

**Make the first save useful.** Give your agent a real project decision, a
working preference or a small goal. The packaged skill asks short questions,
saves selected answers as source notes and can create a task linked to your goal.
It must read the saved records back before reporting success.

Then open a new session connected to the same vault and scope. Ask it to use
Remember, Dammit. to recall that fact **without supplying the answer again**.
This is explicit recall; automatic session-start memory loading is not installed.

## What you can keep

| When this happens | Use the vault to… |
| --- | --- |
| “We already decided this.” | Recall the decision and the source behind it. |
| “Actually, we changed our minds.” | Correct it while retaining the previous version. |
| “I'm picking this up on another machine.” | Exchange memory between copies of the same vault. |
| “That's from a different project.” | Keep project scopes separate; grant personal notes explicitly. |
| “Where did that answer come from?” | Inspect the saved source, revision and correction history. |

Notes are readable Markdown with immutable revisions. Your client uses local
CLI/MCP tools to access them. The core needs no model API key, hosted memory
service, Jev or Laya; your AI client continues to use its normal account.

## Try it without an AI client

The demo saves an email-provider decision, corrects it, reopens the vault and
finds the current decision using the former provider's name. It also checks
that another project cannot recall the record. It uses synthetic data in a new
directory and refuses an existing destination.

<details>
<summary>macOS / Linux</summary>

```sh
git clone https://github.com/Grit-77/remember-dammit.git
cd remember-dammit
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python examples/demo.py --vault .local/demo-vault
```

</details>

<details>
<summary>Windows · PowerShell</summary>

```powershell
git clone https://github.com/Grit-77/remember-dammit.git
cd remember-dammit
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/python.exe examples/demo.py --vault .local/demo-vault
```

</details>

The command prints the actual JSON result. A [captured run](docs/evidence/core-demo-2026-10-11.json)
recalled `Use Postmark for Atlas email.` using the old query `SendGrid email`,
retained `history_states: ["superseded", "active"]`, and returned
`other_project_records: 0`.
Use a different new directory for another run. [Full installation](docs/INSTALL.md)
adds the optional MCP dependency for an AI client.

## Bring your client, keep your scope

| Client | Current evidence |
| --- | --- |
| Codex CLI | Native save/recall tested on Windows, macOS and Linux in a private synthetic run. |
| Claude Code | Workspace setup and SDK protocol checks; native trials blocked before tool use. |
| Cursor / Antigravity | Configuration and SDK checks; native client acceptance remains open. |
| Other MCP/CLI clients | The interfaces are available; compatibility needs its own verification. |

[Native test report and limits](docs/LIVE-ACCEPTANCE.md) · [Current status](docs/STATUS.md)

## Use it across machines

Initialize one vault, then create replicas of that identity. Independent offline
contributions merge; competing corrections remain visible until an explicit
resolution includes every observed head. Old copies cannot silently cancel a
known retraction or access revocation. Locks and indexes stay machine-local.

Use [reviewed transfer bundles or your own file transport](docs/MULTI-MACHINE.md).
A private three-host Syncthing trial is documented in the native test report.
The package does not install a background sync service. Raw sync is not atomic,
and it cannot detect a completely unknown branch that never arrived.
Existing v1 vaults need the guide's previewed, backed-up migration for these features.

## Start small, add what you need

- [Browse and edit working notes](docs/WORKING-NOTES.md): a separate Markdown workspace with previewed corrections.
- [Import or export Markdown](docs/INSTALL.md): copy selected source notes in, or create a scoped readable snapshot.
- [Choose an optional advisor](docs/PROVIDERS.md): Jev or Laya can provide explicit shadow assessment. Neither is required or enabled by setup alone.
- [Inspect the vault format](docs/VAULT.md): sources, history, scope, conflicts and recovery boundaries.

This is an alpha. Capture and recall are deliberate actions. Automatic hooks,
editor text merge and embeddings are not included; large-vault performance is
not benchmarked. Canonical revision files are immutable—use the supported
working-note workflow to edit. [Implementation details and evidence](FACTS.md)

## Tried it? Tell us where it broke

[Share your first-run experience](https://github.com/Grit-77/remember-dammit/issues/new?template=first-run.yml):
could your agent save a useful fact and recall it in a fresh session? Where did
you get stuck? Keep private notes and credentials out of the report.

If it earns a place in your workflow, consider starring the repository.
