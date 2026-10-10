# Install the source alpha

This is a runnable **0.1.0a2 source alpha**. Its CLI, local stdio MCP server and
configuration proposal generator share one local vault. The four named clients
are integration targets: Claude Code, Codex, Cursor and Google Antigravity still
need real-client acceptance. Every generated proposal says `tested_live: false`.
Parsed configuration and SDK subprocess checks do not establish that a client
loaded the server, followed the skill or recalled memory in a fresh session.

For the guided repository-link workflow, start with [AGENT-SETUP.md](AGENT-SETUP.md). It includes optional advisor selection and a first-use interview. The commands below also support manual setup.

## Prepare a local environment

Use Python 3.11 or newer, in the repository checkout. On Windows PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[mcp]"
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" init
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" doctor
```

On macOS/Linux use `.venv/bin/python` for the same commands and an absolute vault
path such as `/home/owner/Memory Vault`. The core alone can be installed with
`pip install -e .`; the `mcp` extra is required for the server. An MCP client must
launch the interpreter containing the installed package. A source checkout in
the current working directory is insufficient when the client starts elsewhere.
The memory core makes no provider calls and needs no model API key.

## Preview a configuration

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" integration codex --project demo --python-executable "C:/path/to/remember-dammit/.venv/Scripts/python.exe"
```

Replace `codex` with `claude`, `cursor` or `antigravity`. Use exactly one project
ID or `--personal`. A project server reads its project, shared records and
explicitly granted personal records; personal mode is an explicit owner choice
and does not expose every project. The server's selection is fixed at launch.

The CLI prints a JSON proposal containing `config_format`, `config_text`,
`skill_text`, `instructions`, `harness` and `tested_live`. It writes no installed
settings, vault files or trust decisions. Extract **only `config_text`** to merge
configuration; the outer proposal is not a client configuration file. Its
`command` names one interpreter, and `args` is an array equivalent to:

```text
python -m remember_dammit --vault ABSOLUTE_VAULT_PATH mcp --project PROJECT_ID
```

Personal proposals replace the final pair with `--personal`. Keep command and
arguments separate: no shell wrapper is needed. Spaces, quotes, backslashes and
Unicode remain literal. Use absolute paths; the renderer does not resolve `~`,
environment variables or relative paths. `${...}` values are rejected because
some clients interpolate them independently of JSON escaping. Empty selections,
conflicting selections and control characters are rejected as structured errors.

## Merge into your chosen local client

Back up the active file and resolve an existing `remember-dammit` entry before
merging. Add only our entry and an optional new skill file; preserve other server
entries, custom rules, `AGENTS.md`, `CLAUDE.md` and native tool permissions.
`~` below denotes your user home directory, not a literal path in emitted argv.

| Client | Configuration and optional shared skill |
| --- | --- |
| Claude Code | Merge JSON `mcpServers.remember-dammit` into project `.mcp.json`. User MCP entries live in `~/.claude.json`; prefer Claude's native manager for that scope. Save `skill_text` as `.claude/skills/remember-dammit/SKILL.md` or its home equivalent. Complete interactive workspace trust/project approval and inspect `/mcp`. |
| Codex | Merge TOML `[mcp_servers.remember-dammit]` into `.codex/config.toml` for a trusted project or `~/.codex/config.toml` (custom `CODEX_HOME` changes the user root). Save the skill under `.agents/skills/remember-dammit/SKILL.md` or `~/.agents/skills/remember-dammit/SKILL.md`. Restart the client and inspect its MCP list. |
| Cursor | Merge JSON into `.cursor/mcp.json` or `~/.cursor/mcp.json`. Save the skill under `.cursor/skills/remember-dammit/SKILL.md` or `.agents/skills/remember-dammit/SKILL.md`; home equivalents are documented too. Reload the selected local IDE/CLI and inspect available MCP tools. |
| Antigravity | In IDE, use **MCP Servers → Manage MCP Servers → View raw config**. Current docs name global `~/.gemini/config/mcp_config.json` and workspace `.agents/mcp_config.json`; confirm the active file in your installed version. Merge JSON there. Use workspace `.agents/skills/remember-dammit/SKILL.md`; global skills differ by surface. Refresh the MCP list. |

Official formats and locations were inspected on 2026-10-10. Version, platform
and local/remote/cloud surfaces can differ. Complete approvals through the chosen
client. A generated skill supplies an explicit recall/save/correct/history
routine; no hooks or automatic start/resume/compaction/stop context is installed.
The foundation MCP server writes only its fixed personal or project scope;
session scopes are not exposed through that server.

## Verify and remove

Ask the attached client to explicitly `remember` a harmless disposable decision,
then test `recall` in a fresh session, `show`, `correct` with the expected revision,
predecessor-term recall and `history`. Check project/session isolation, error
fallback and uninstall using disposable vaults. Record the client version,
platform, surface, transport and native trust state with actual results. All
four clients must pass the explicit baseline in [HARNESSES.md](HARNESSES.md)
before a broad four-client support claim. That live matrix remains pending.

For local development checks:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

If attach fails, check the interpreter's package/MCP installation and the exact
vault/selection. Run `--help` and explicit CLI recall using the same selection as
a fallback; report errors instead of inventing remembered content. MCP writes
need an initialized vault. Installing a proposal does not initialize one.

To uninstall, remove only the server entry and skill file you added, refresh the
client, and restore your backup if necessary. Keep the vault unless you explicitly
intend to delete your memory. The workspace setup helper can install the configuration and skill; uninstall remains manual.

## Browse a Markdown snapshot

The local Python API can export an initialized vault into a **new** directory
outside the canonical vault. Its parent must already exist; existing files or
directories are never overwritten. Symlink and Windows junction ancestors are
rejected; supply a canonical path when ordinary aliases such as macOS `/var`
introduce a symlink ancestor. For example, run this with the installed package's interpreter:

```python
from remember_dammit.storage import Vault
from remember_dammit.exporting import export_snapshot

result = export_snapshot(
    Vault("C:/Memory Vault"),
    "C:/Exports/memory-atlas-2026-10-10",  # C:/Exports already exists
    project="atlas",
)
print(result["home"])
```

Open the exported `Home.md` in a Markdown browser. Every note has structured YAML
metadata, its original UTF-8 body, source links and any exported history links.
The snapshot follows the same owner-local disclosure, project and grant selection
as retrieval. Records with unavailable or inactive source dependencies are
withheld transitively; hidden source/predecessor IDs are never emitted as links.
The default exports active records and excludes raw sources cited only by
superseded/retracted records. `include_history=True` also admits eligible
historical/proposed records, visibly labeled by their state. Use `personal=True`
instead of `project` for the explicit personal/shared selection.

**Snapshot edits do not update the live vault.** Copying an export elsewhere
discloses its included content, including permitted private records. A successful
export has `COMPLETE.md` and no `INCOMPLETE.md`. If the vault or sharing policy
changes while exporting, the operation fails and leaves `INCOMPLETE.md`; it takes
precedence over any completion marker. Partial exports are not completed snapshots.
The exporter does not repair sources or delete incomplete output automatically.
Finalization checks the snapshot and removes the incomplete marker under the
vault's cooperating writer lock; the vault parent needs access for that local
lock directory. A revocation after this completion point cannot retract bytes
already exported. Arbitrary external editors do not participate in the lock.

## Import existing Markdown

Keep the original folder and the new canonical vault separate. Preview before applying:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" import-plan --source "C:/Existing Notes" --collection notes --scope project:demo | Set-Content -Encoding utf8NoBOM .local/import-plan.json
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" import-apply --plan .local/import-plan.json
```

This PowerShell 7 example assumes `.local` already exists. Inspect the JSON preview's files, exclusions, scope and actions before applying. On another shell, save stdout as UTF-8 without a BOM. The plan contains local paths: keep it private. You may omit `--vault` for a source-only preview before initializing a target.

Imports store UTF-8 Markdown as private source-excerpt records; frontmatter remains source text and cannot grant access. Hidden/system folders, links/junctions, invalid UTF-8 and nonportable paths are excluded. Limits are 1 MiB per file, 16 MiB admitted content, 1,000 files and 10,000 scanned entries. Split larger collections explicitly.

Generate a fresh plan against the target for changed files. The same collection, scope and relative path retain one record ID; changes use corrections. A repeated unchanged plan is idempotent. Removed source files do not delete imported memory. This is copy-in adoption, not two-way synchronization.

Application rechecks source content and expected target revisions. A batch can report `status: partial`; check `completed`, `failed_index` and the error before retrying. Completed records remain in the vault. Never equate process exit alone with a completed import.
