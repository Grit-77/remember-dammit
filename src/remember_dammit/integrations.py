"""Read-only, local stdio MCP configuration proposals.

Official configuration shapes were inspected on 2026-10-10. Parsing a
proposal is not evidence that any installed client has accepted it.
"""

import json
from importlib.resources import files
import os
import sys

from .errors import VaultError
from .validation import validate_identifier


_HARNESS_INSTRUCTIONS = {
    "claude": (
        "Merge only mcpServers.remember-dammit into .mcp.json at the project root. "
        "For user scope, Claude Code stores mcpServers in ~/.claude.json; prefer its native MCP manager.",
        "Optionally save skill_text as .claude/skills/remember-dammit/SKILL.md "
        "or ~/.claude/skills/remember-dammit/SKILL.md. Preserve existing instructions.",
        "Open Claude Code interactively to complete workspace trust and project MCP approval, "
        "then inspect /mcp. Do not bypass native permissions.",
    ),
    "codex": (
        "Merge the mcp_servers.remember-dammit table into project .codex/config.toml "
        "or ~/.codex/config.toml (under CODEX_HOME when customized). "
        "Project configuration requires a trusted project.",
        "Optionally save skill_text as .agents/skills/remember-dammit/SKILL.md "
        "or ~/.agents/skills/remember-dammit/SKILL.md. Preserve existing instructions.",
        "Restart the relevant Codex client and inspect its MCP server list or /mcp. "
        "Complete native trust and tool approvals in the client.",
    ),
    "cursor": (
        "Merge only mcpServers.remember-dammit into project .cursor/mcp.json "
        "or ~/.cursor/mcp.json. Select the intended local IDE or CLI surface.",
        "Optionally save skill_text as .cursor/skills/remember-dammit/SKILL.md "
        "or .agents/skills/remember-dammit/SKILL.md; user equivalents are under ~/.cursor/skills "
        "or ~/.agents/skills. Preserve existing instructions.",
        "Reload the chosen local client and inspect its MCP tools. "
        "Complete native approvals; local files do not establish cloud compatibility.",
    ),
    "antigravity": (
        "In Antigravity IDE open MCP Servers > Manage MCP Servers > View raw config. "
        "Current docs name ~/.gemini/config/mcp_config.json for global configuration "
        "and workspace .agents/mcp_config.json. Merge only mcpServers.remember-dammit "
        "into the active file; confirm the location in your installed version.",
        "Optionally save skill_text as .agents/skills/remember-dammit/SKILL.md. "
        "Global skills differ by surface: ~/.gemini/config/skills for 2.0/IDE, "
        "~/.gemini/antigravity-cli/skills for CLI. Preserve existing instructions.",
        "Refresh the chosen client's MCP server list and complete native approvals. "
        "A proposal does not establish acceptance on every Antigravity surface.",
    ),
}




def _literal(value, name):
    """Validate a literal argument without expanding paths or client variables."""
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value.strip():
        raise VaultError("invalid_argument", f"{name} must be a nonempty string or path.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise VaultError("invalid_argument", f"{name} cannot contain control characters.")
    if "${" in value:
        raise VaultError("invalid_argument", f"{name} cannot contain client variable interpolation.")
    return value


def render(harness, *, vault_path, project=None, personal=False, python_executable=None):
    """Return a proposal only; do not read/write installed settings or the vault.

    Specify exactly one of project or personal=True. The executable defaults to
    this interpreter; install the package and MCP extra in that interpreter first.
    Paths are literal and are neither resolved nor checked for existence.
    """
    if not isinstance(harness, str) or harness not in _HARNESS_INSTRUCTIONS:
        raise VaultError("invalid_harness", "Choose claude, codex, cursor, or antigravity.")
    if not isinstance(personal, bool) or (project is not None) == personal:
        raise VaultError("invalid_selection", "Select exactly one project or personal mode.")
    if project is not None:
        if not isinstance(project, str):
            raise VaultError("invalid_selection", "Project must be a nonempty identifier.")
        project = _literal(project, "project")
        project = validate_identifier(project, "Project ID")
    vault_path = _literal(vault_path, "vault_path")
    if vault_path.startswith("-"):
        raise VaultError("invalid_argument", "Vault path cannot start with an option prefix; use an absolute path.")
    executable = _literal(sys.executable if python_executable is None else python_executable, "python_executable")
    args = ["-m", "remember_dammit", "--vault", vault_path, "mcp"]
    args.extend(["--project", project] if project is not None else ["--personal"])
    server = {"command": executable, "args": args}
    if harness == "codex":
        config_format = "toml"
        # JSON strings without Unicode ASCII escaping are also TOML basic
        # strings here: controls are rejected and quotes/backslashes escaped.
        config_text = (
            "[mcp_servers.remember-dammit]\n"
            f"command = {json.dumps(executable, ensure_ascii=False)}\n"
            f"args = {json.dumps(args, ensure_ascii=False)}\n"
        )
    else:
        config_format = "json"
        if harness == "claude":
            server["type"] = "stdio"
        config_text = json.dumps({"mcpServers": {"remember-dammit": server}}, ensure_ascii=False, indent=2) + "\n"
    instructions = [
        "Proposal only: no installed settings, vault content, rules, skills, or trust state were changed. "
        "Live client acceptance remains pending (tested_live=false).",
        "Install remember-dammit with its MCP extra in the command interpreter. Use absolute vault "
        "and interpreter paths for a portable local launch; tilde and environment variables are not expanded. "
        "Keep command and args separate; never wrap this configuration in a shell command.",
        *_HARNESS_INSTRUCTIONS[harness],
        "Back up the active configuration before manually merging. Preserve other entries and custom "
        "instructions; resolve an existing remember-dammit name collision before installing. "
        "To uninstall, remove only the entry and skill you added and restore your backup if needed.",
    ]
    return {
        "harness": harness,
        "config_format": config_format,
        "config_text": config_text,
        "skill_text": files("remember_dammit").joinpath("templates/remember-dammit/SKILL.md").read_text(encoding="utf-8"),
        "instructions": instructions,
        "tested_live": False,
    }
