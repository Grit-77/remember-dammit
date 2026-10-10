"""Read-only project installation checks; native client acceptance stays pending.

Inspect only the chosen workspace paths, an explicitly selected local runtime,
and the selected vault. Never execute commands from client configuration or
return its contents, parser diagnostics, runtime output, or vault records.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from .errors import VaultError
from .integrations import render
from .setup import _PATHS, _absolute, _invalid_constant, _json_object, _no_links, _overlaps, _snapshot
from .storage import Vault


def _check(name, status, code, message, path):
    return {"name": name, "status": status, "code": code, "message": message, "path": str(path)}


def _config_check(path, proposal, snapshots):
    try:
        snapshot = _snapshot(path)
        snapshots.append(("config", path, snapshot))
        if snapshot is None:
            return _check("config", "missing", "missing_config", "Install the selected workspace configuration with the setup command.", path)
        text = snapshot[0].decode("utf-8")
        if proposal["config_format"] == "toml":
            value = tomllib.loads(text)
            expected = tomllib.loads(proposal["config_text"])
            key = "mcp_servers"
        else:
            value = json.loads(text, object_pairs_hook=_json_object, parse_constant=_invalid_constant)
            expected = json.loads(proposal["config_text"])
            key = "mcpServers"
        if not isinstance(value, dict) or not isinstance(value.get(key, {}), dict):
            raise ValueError
        servers = value.get(key, {})
        if "remember-dammit" not in servers:
            return _check("config", "missing", "missing_server", "Install the remember-dammit entry in this workspace with the setup command.", path)
        if servers["remember-dammit"] != expected[key]["remember-dammit"]:
            return _check("config", "conflict", "server_conflict", "Resolve the existing server entry manually; its runtime, vault, or selection differs from the requested configuration.", path)
        return _check("config", "ready", "config_ready", "The selected server entry matches the requested local configuration.", path)
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError):
        return _check("config", "error", "invalid_config", "Correct the selected configuration's syntax and server table manually, then inspect again.", path)
    except VaultError as exc:
        return _file_error("config", path, exc)
    except OSError:
        return _check("config", "error", "unreadable_config", "Make the selected configuration readable, then inspect again.", path)


def _file_error(name, path, error):
    code = "concurrent_change" if error.code == "concurrent_change" else "unsafe_path"
    return _check(name, "error", code, "Use regular workspace files without links or junctions; if a file changed during inspection, retry.", path)


def _skill_check(path, proposal, snapshots):
    try:
        snapshot = _snapshot(path)
        directory_entries = None
        if path.parent.exists():
            _no_links(path.parent)
            if not path.parent.is_dir():
                return _check("skill", "conflict", "skill_conflict", "Resolve the custom remember-dammit skill directory manually before installing the packaged skill.", path)
            directory_entries = frozenset(path.parent.iterdir())
        snapshots.append(("skill", path, snapshot, directory_entries))
        if directory_entries is not None and directory_entries != ({path} if snapshot is not None else set()):
            return _check("skill", "conflict", "skill_conflict", "Resolve the custom remember-dammit skill directory manually before installing the packaged skill.", path)
        if snapshot is None:
            return _check("skill", "missing", "missing_skill", "Install the packaged workspace skill with the setup command.", path)
        if snapshot[0] != proposal["skill_text"].encode("utf-8"):
            return _check("skill", "conflict", "skill_conflict", "Resolve the existing skill manually; it differs from the packaged skill.", path)
        return _check("skill", "ready", "skill_ready", "The installed skill matches the packaged skill.", path)
    except VaultError as exc:
        return _file_error("skill", path, exc)
    except OSError:
        return _check("skill", "error", "unreadable_skill", "Make the selected skill readable, then inspect again.", path)


def _runtime_check(executable, workspace):
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise OSError
        # Isolate the selected interpreter from workspace imports and suppress
        # bytecode writes. Import only; no server/provider/client launch.
        result = subprocess.run(
            [str(executable), "-I", "-B", "-c", "import remember_dammit; import remember_dammit.mcp_server"],
            cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False,
        )
        if result.returncode != 0:
            raise OSError
        return _check("runtime", "ready", "runtime_ready", "The selected interpreter imports remember-dammit and its MCP server.", executable)
    except subprocess.TimeoutExpired:
        return _check("runtime", "error", "runtime_timeout", "The import probe timed out; repair the selected Python environment and inspect again.", executable)
    except (OSError, subprocess.SubprocessError):
        return _check("runtime", "missing", "missing_runtime", "Install remember-dammit with its MCP extra in the selected interpreter, then inspect again.", executable)


def _vault_check(path):
    try:
        if not path.exists():
            return _check("vault", "missing", "missing_vault", "Explicitly initialize the selected vault, then inspect again.", path)
        report = Vault(path).doctor()
        if not report["ok"]:
            return _check("vault", "error", "integrity_error", "Run vault doctor locally and resolve its integrity or source issues before using this installation.", path)
        return _check("vault", "ready", "vault_ready", "The selected initialized vault passes its read-only doctor check.", path)
    except VaultError as exc:
        code = "invalid_vault" if exc.code == "invalid_vault" else "integrity_error"
        return _check("vault", "error", code, "Run vault doctor locally; verify the selected path and repair the vault's layout or committed data.", path)
    except OSError:
        return _check("vault", "error", "unreadable_vault", "Make the selected vault readable, then run vault doctor locally.", path)


def inspect_workspace(workspace, harness, *, vault_path, project=None, personal=False,
                      python_executable=None) -> dict:
    """Report local readiness without installing, repairing, or changing trust.

    Invalid caller selections and unsafe paths raise ``VaultError``. Installed
    file/runtime/vault problems produce independent checks. Local readiness
    never establishes live client acceptance or native trust/tool approval.
    """
    workspace = _absolute(workspace, "workspace")
    vault_path = _absolute(vault_path, "vault_path")
    executable = _absolute(sys.executable if python_executable is None else python_executable,
                           "python_executable", interpreter=True)
    if not workspace.is_dir() or workspace == Path(workspace.anchor) or workspace == Path.home().resolve():
        raise VaultError("unsafe_path", "Choose an existing project workspace, not a home or filesystem root.")
    if _overlaps(workspace, vault_path) or executable.is_relative_to(vault_path) or executable.resolve().is_relative_to(vault_path):
        raise VaultError("unsafe_path", "The workspace, vault, and runtime must not create overlapping managed paths.")
    proposal = render(harness, vault_path=vault_path, project=project, personal=personal,
                      python_executable=executable)
    config_relative, skill_relative = _PATHS[harness]
    snapshots = []
    checks = [
        _config_check(workspace / config_relative, proposal, snapshots),
        _skill_check(workspace / skill_relative, proposal, snapshots),
        _runtime_check(executable, workspace),
        _vault_check(vault_path),
    ]
    # Do not publish readiness based on client files that changed while the
    # bounded runtime and vault probes ran. Rechecking never writes a file.
    for observation in snapshots:
        name, path, snapshot = observation[:3]
        try:
            if _snapshot(path) != snapshot:
                raise VaultError("concurrent_change", "The inspected file changed.")
            if name == "skill":
                _no_links(path.parent)
                current_entries = frozenset(path.parent.iterdir()) if path.parent.is_dir() else None
                if current_entries != observation[3]:
                    raise VaultError("concurrent_change", "The inspected skill directory changed.")
        except (OSError, VaultError) as exc:
            replacement = _file_error(name, path, exc) if isinstance(exc, VaultError) else _check(name, "error", "concurrent_change", "The inspected file became unreadable; retry inspection.", path)
            checks = [replacement if item["name"] == name else item for item in checks]
    ready = all(item["status"] == "ready" for item in checks)
    return {
        "status": "ready" if ready else "not_ready", "ready": ready,
        "workspace": str(workspace), "harness": harness, "vault_path": str(vault_path),
        "selection": {"project": project, "personal": personal},
        "python_executable": str(executable), "checks": checks,
        "tested_live": False, "native_approval": "pending",
        "next_steps": [
            "Resolve any missing, conflicting, or failed local checks and inspect again.",
            "Reload the selected client, complete native workspace trust and MCP/tool approvals, and inspect its server list and tool schemas.",
            "Run an approved save-and-read-back interaction in that client to verify live acceptance.",
        ],
    }
