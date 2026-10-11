# Install through your agent

Paste this into Claude Code, Codex, Cursor, or Antigravity in the project where
you want to use memory:

> Install https://github.com/Grit-77/remember-dammit for this workspace. Use an
> existing Python 3.11+ and a dedicated virtual environment. Ask me which vault
> and memory scope to use, preview the workspace setup, then apply the requested
> configuration. Help me save one useful fact and actually read it back. Then
> ask a few short questions to get to know me, save my selected answers as source
> notes, create one task from my goal, and read it back. After this first-use
> check, ask whether I want no optional advisor, Jev, or Laya, explain what is
> available, and help me with the next setup steps.

The agent should carry out the installation and explain the result. This helper
does not download Python, create a virtual environment, install packages, or
change global client settings. Those installation steps use ordinary commands
in an explicitly selected checkout. The current implementation provides a local
vault, scoped MCP tools, and a workspace skill. Optional Jev/Laya shadow
assessment uses a separate explicit owner CLI command and configuration.

## Questions to settle before installation

Use the visible client/workspace and sensible dedicated checkout/runtime defaults
when known, and present the chosen paths briefly. Ask only for genuinely missing
information, using short questions in the user's language:

1. Which local client and existing project workspace should use memory?
2. Present the dedicated checkout/runtime location; ask only if no suitable
   location can be inferred or the user's preference affects the install.
3. Which absolute vault directory should be used? Reuse an initialized vault,
   or initialize a new/empty directory deliberately outside the workspace.
4. Should the MCP server use this project ID or the user's personal selection?

The selection fixes both visible memory and write scope. A project selection
cannot write a global personal profile. Keep the vault separate from the
workspace and runtime. Do not include credentials in any answer saved as memory.

## Ordinary installation commands

These are examples; replace the three paths and project ID with the user's
chosen values. Check existing directories before cloning. If the checkout
already exists, inspect its source and revision rather than overwriting it.
Use the existing Python installation; do not enable paid services or download
a replacement runtime automatically.

PowerShell:

```powershell
git clone https://github.com/Grit-77/remember-dammit.git C:\Tools\remember-dammit
Set-Location C:\Tools\remember-dammit
python -m venv --copies .venv
& .\.venv\Scripts\python.exe -m pip install '.[mcp]'
$rdPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$rdWorkspace = 'C:\Projects\my-project'
$rdVault = 'C:\Memory\remember-dammit'
& $rdPython -m remember_dammit --vault $rdVault init
& $rdPython -m remember_dammit --vault $rdVault setup codex --workspace $rdWorkspace --project my-project --python-executable $rdPython
& $rdPython -m remember_dammit --vault $rdVault setup codex --workspace $rdWorkspace --project my-project --python-executable $rdPython --apply
```

On macOS/Linux, use an existing `python3`, create the environment with
`python3 -m venv .venv`, and invoke the absolute `.venv/bin/python`
for the same module commands. Keep the default POSIX interpreter links: forcing
`--copies` can break relocatable Python installations. The setup helper supports
a normal linked POSIX venv executable and preserves its command path. Other selected paths and executable
parent directories must not contain links or Windows junctions.

Replace `codex` with `claude`, `cursor`, or `antigravity` for the selected client.
For personal selection, replace `--project my-project` with `--personal`.
Without `--apply`, setup is a validated dry run and creates no files. Review the
proposed paths before applying. Package installation is separate from this dry
run and may already have changed the chosen checkout's virtual environment.

## What workspace setup writes

| Client | Project MCP configuration | Installed workspace skill |
| --- | --- | --- |
| Claude Code | `.mcp.json` | `.claude/skills/remember-dammit/SKILL.md` |
| Codex | `.codex/config.toml` | `.agents/skills/remember-dammit/SKILL.md` |
| Cursor | `.cursor/mcp.json` | `.cursor/skills/remember-dammit/SKILL.md` |
| Antigravity | `.agents/mcp_config.json` | `.agents/skills/remember-dammit/SKILL.md` |

The helper adds only the `remember-dammit` server entry and skill. JSON merges
preserve unrelated settings semantically; an actual merge may change whitespace.
TOML retains the original bytes and appends the server table when possible. If
the existing TOML structure cannot be extended safely, setup refuses it.
An identical existing entry and skill are a no-op. A different entry, custom
skill, malformed configuration, linked target, stale snapshot, invalid vault,
or missing MCP runtime is refused. Existing `AGENTS.md` and custom instructions
are not setup targets.

Before applying, setup saves existing changed files and a receipt outside both
workspace and vault. The default machine-local location is
`%LOCALAPPDATA%/remember-dammit/setup` on Windows or
`${XDG_STATE_HOME:-~/.local/state}/remember-dammit/setup` on macOS/Linux.
New-file entries in the receipt record that no original file existed. The setup
result includes each backup path and readback hash. On write failure it attempts
to restore changed files and remove newly created setup directories. It refuses
to overwrite a concurrent owner edit during rollback and reports any remaining
failure in its local evidence. Inspect that receipt before retrying.

## Native approval and first readback

Reload the chosen client, complete its native workspace trust and MCP tool
approvals, and inspect its MCP server list. Antigravity users should confirm
that the installed client reads the chosen workspace configuration. Successful
file setup reports `tested_live=false`; it does not prove client acceptance.

Use `setup-check` with the same client, workspace, vault and selection to diagnose
the configuration, skill, runtime and vault before attaching the client. This
read-only report does not repair files or establish native approval.

Inspect the exposed schemas, then use the packaged skill for a short interview:

- Ask what the user is working toward, how they prefer help, and which small
  task to start with. Allow questions to be skipped.
- Save only selected, authorized answers as `kind="source"` records with
  `evidence="user-statement"`. Preserve the question and actual answer.
- If deriving a preference or decision, link its `sources` to the saved source
  IDs. Keep inferred conclusions `state="proposed"` with
  `evidence="agent-inference"`.
- Create one `kind="task"` record from the supplied goal, with an open status
  and a small next action. This creates a task note, not a scheduled job.
- Call `show` for the returned source and task IDs and `recall` for a distinctive
  phrase. Report the actual returned IDs and content; distinguish a direct read
  from a successful search. A missing server or failed readback is a blocker.

Do not claim saving based on intended tool arguments. Do not claim automatic
fresh-session recall or lifecycle hooks; the agent deliberately queries memory.

## Ask about optional advisors, then explain and help

Explicitly ask after the core installation unless the user already made this
choice in the current conversation:

> Would you like to continue without an advisor, choose Jev, or choose Laya?
> Core memory works on its own. Jev may require remote credentials and metered
> usage; Laya needs a separately installed compatible local server and suitable
> hardware. Setup records your choice; assessment requires separate configuration
> and an explicit command, and cannot change your memory or recall order.

Let the user choose. `--advisor none`, `--advisor jev`, or `--advisor laya`
records the requested choice in the setup report only. For example, repeat the
same setup command with `--advisor laya`; an unchanged installation remains a
no-op. The result is `enabled=false`, `connector_available=true` and
`setup_status="not_configured"` for Jev/Laya,
or `setup_status="disabled"` for none. This choice is not authorization to
activate paid usage, buy credits, call a provider, or put keys in notes.
The report always includes `choice_confirmed=false`: a CLI value, including the
default `none`, cannot prove a user's conversational preference. Ask the optional
question unless the user explicitly answered it in the conversation.

Then give the user the relevant guidance:

- **None:** explain how to recall a note, save a decision, correct a record, and
  read the first task. No provider is needed for the local memory tools.
- **Jev:** follow [PROVIDERS.md](PROVIDERS.md) to explain hosted requests and
  billing, generate the disabled configuration template, and help identify the
  intended account and environment-variable setup. Keep credentials outside the
  vault. Preview eligible requests and obtain explicit query-transfer approval
  before a live call. Never relabel private notes or enable paid usage silently.
- **Laya:** follow [PROVIDERS.md](PROVIDERS.md) to inspect an existing local server
  or explain separate provisioning and model downloads. Generate its disabled
  configuration template, select the checkpoint, and preview the loopback
  request. An installed package or healthy server is not proof of a successful
  assessment; inspect the actual result and report failures.

Finish by explaining the selected scope, installed files, verified readbacks,
current local memory tools, optional connector status, and next action. If the
client has not yet accepted MCP, say approval and live verification remain
pending and guide the user through that client step.

## Python helper API

```python
from remember_dammit.setup import setup_workspace

report = setup_workspace(
    absolute_workspace, "codex",
    vault_path=absolute_initialized_vault,
    project="my-project",  # or project=None, personal=True
    python_executable=absolute_installed_mcp_python,
    advisor="none",       # explicit optional choice; never activates a provider
    dry_run=True,
)
```

On apply, the report describes `configured` or `unchanged` local files. A
`VaultError` has a stable error code; write failures may attach an `evidence`
dictionary with rollback results and the machine-local receipt path.

## Using the same memory on multiple machines

Install the runtime separately on each machine. Initialize one format-2 vault, then copy that vault identity and its immutable files to the other machines; do not initialize unrelated vaults and expect them to merge. Choose the local absolute vault/interpreter paths separately in each workspace configuration. Claude and Codex may use the same local vault with their own fixed project selections.

Follow [MULTI-MACHINE.md](MULTI-MACHINE.md) for reviewed transfer bundles, exact-head conflict resolution, machine-local state, and previewed legacy migration. Stop old clients before migration; keep the original and backup until the new copy has been checked. Runtime setup does not migrate existing data or enable a synchronization service.
