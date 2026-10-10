"""Explicit, project-only client setup with conflict refusal and rollback.

This helper installs neither Python nor packages. It never calls a provider or
changes client trust. The caller supplies an already installed MCP interpreter.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib
import uuid

from .errors import VaultError
from .integrations import render
from .storage import Vault


_PATHS = {
    "claude": (".mcp.json", ".claude/skills/remember-dammit/SKILL.md"),
    "codex": (".codex/config.toml", ".agents/skills/remember-dammit/SKILL.md"),
    "cursor": (".cursor/mcp.json", ".cursor/skills/remember-dammit/SKILL.md"),
    "antigravity": (".agents/mcp_config.json", ".agents/skills/remember-dammit/SKILL.md"),
}
_UNSET = object()


def _no_links(path):
    """Check the entire lexical ancestry, including Windows junctions."""
    for part in reversed((path, *path.parents)):
        try:
            metadata = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise VaultError("unsafe_path", "Setup paths must not contain links or junctions.")


def _absolute(value, label, *, interpreter=False):
    try:
        raw = os.fspath(value)
        if not isinstance(raw, str) or not raw.strip() or any(ord(c) < 32 or ord(c) == 127 for c in raw) or "${" in raw:
            raise ValueError
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError
        # POSIX venvs commonly link their executable. Keep that lexical command:
        # resolving it would launch the base interpreter without the venv.
        _no_links(path.parent if interpreter else path)
        return path if interpreter else path.resolve()
    except (TypeError, ValueError, OSError):
        raise VaultError("unsafe_path", f"{label} must be an absolute, literal path without parent traversal.") from None


def _overlaps(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _snapshot(path):
    _no_links(path)
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise VaultError("unsafe_path", "Setup targets must be regular files without hard links.")
        data = path.read_bytes()
        after = path.stat()
        identity = (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_mode)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode):
            raise VaultError("concurrent_change", "A setup target changed while it was read; retry.")
        return data, identity
    except FileNotFoundError:
        return None


def _ensure_snapshot(path, expected):
    if _snapshot(path) != expected:
        raise VaultError("concurrent_change", "A setup target changed after planning; retry without overwriting it.")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Nonstandard JSON value")


def _config_bytes(original, proposal):
    """Preserve unrelated JSON meaning and all original TOML bytes."""
    old = b"" if original is None else original[0]
    try:
        if proposal["config_format"] == "toml":
            data = tomllib.loads(old.decode("utf-8"))
            wanted = tomllib.loads(proposal["config_text"])["mcp_servers"]["remember-dammit"]
            servers = data.get("mcp_servers", {})
            if not isinstance(servers, dict):
                raise ValueError
            if "remember-dammit" in servers:
                if servers["remember-dammit"] != wanted:
                    raise VaultError("setup_conflict", "An existing remember-dammit server differs; resolve it manually.")
                return old
            output = old + (b"\n" if old and not old.endswith(b"\n") else b"") + b"\n" + proposal["config_text"].encode("utf-8")
            merged = tomllib.loads(output.decode("utf-8"))
            # Inline tables cannot be extended with an appended table. The
            # parser rejects them rather than rewriting owner formatting.
            if merged["mcp_servers"]["remember-dammit"] != wanted:
                raise ValueError
            return output
        data = json.loads(old.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_constant) if original is not None else {}
        if not isinstance(data, dict):
            raise ValueError
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError
        wanted = json.loads(proposal["config_text"])["mcpServers"]["remember-dammit"]
        if "remember-dammit" in servers:
            if servers["remember-dammit"] != wanted:
                raise VaultError("setup_conflict", "An existing remember-dammit server differs; resolve it manually.")
            return old
        servers["remember-dammit"] = wanted
        data["mcpServers"] = servers
        return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError):
        raise VaultError("invalid_config", "Existing client configuration cannot be safely merged; correct it manually.") from None


def _runtime_check(executable, workspace):
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise OSError
        result = subprocess.run(
            [str(executable), "-I", "-c", "import remember_dammit; import remember_dammit.mcp_server"],
            cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=False,
        )
        if result.returncode != 0:
            raise OSError
    except (OSError, subprocess.SubprocessError):
        raise VaultError("missing_runtime", "The selected interpreter must already contain remember-dammit with its MCP extra.") from None


def _state_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "remember-dammit" / "setup"


def _mkdirs(path, created):
    _no_links(path)
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise VaultError("unsafe_path", "A setup parent must be a directory.")
    for directory in reversed(missing):
        _no_links(directory)
        directory.mkdir(mode=0o700)
        created.append(directory)


def _atomic_write(path, data, *, expected=_UNSET, mode=0o600):
    _no_links(path)
    temporary = path.parent / (".remember-setup-" + uuid.uuid4().hex)
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(mode)
        _no_links(path)
        if expected is not _UNSET:
            _ensure_snapshot(path, expected)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _receipt(path, value):
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def setup_workspace(workspace, harness, *, vault_path, project=None, personal=False,
                    python_executable=None, advisor="none", dry_run=True) -> dict:
    """Plan or apply exactly one project-scoped MCP entry and managed skill.

    Different existing entries or custom skills are never overwritten. Dry runs
    still validate the runtime but create no files. Exceptions may include an
    ``evidence`` dictionary with the local receipt and rollback result.
    """
    if type(dry_run) is not bool:
        raise VaultError("invalid_argument", "dry_run must be a boolean.")
    if advisor not in ("none", "jev", "laya"):
        raise VaultError("invalid_advisor", "Choose none, jev, or laya explicitly.")
    workspace = _absolute(workspace, "workspace")
    vault_path = _absolute(vault_path, "vault_path")
    executable = _absolute(sys.executable if python_executable is None else python_executable, "python_executable", interpreter=True)
    if not workspace.is_dir() or workspace == Path(workspace.anchor) or workspace == Path.home().resolve():
        raise VaultError("unsafe_path", "Choose an existing project workspace, not a home or filesystem root.")
    if _overlaps(workspace, vault_path) or executable.is_relative_to(vault_path) or executable.resolve().is_relative_to(vault_path):
        raise VaultError("unsafe_path", "The workspace, vault, and runtime must not create overlapping managed paths.")
    proposal = render(harness, vault_path=vault_path, project=project, personal=personal, python_executable=executable)
    # Opening and listing validate the actual initialized layout and committed
    # data; neither initializes nor writes the vault.
    vault = Vault(vault_path)
    vault.list_records()
    config_relative, skill_relative = _PATHS[harness]
    config = workspace / config_relative
    skill = workspace / skill_relative
    config_before = _snapshot(config)
    skill_before = _snapshot(skill)
    if skill.parent.exists():
        _no_links(skill.parent)
        if not skill.parent.is_dir() or set(skill.parent.iterdir()) != {skill}:
            raise VaultError("setup_conflict", "An existing custom skill directory must be resolved manually.")
    skill_data = proposal["skill_text"].encode("utf-8")
    if skill_before is not None and skill_before[0] != skill_data:
        raise VaultError("setup_conflict", "An existing remember-dammit skill differs; resolve it manually.")
    plans = [(config, config_before, _config_bytes(config_before, proposal)), (skill, skill_before, skill_data)]
    for path, _, _ in plans:
        _no_links(path)
    _runtime_check(executable, workspace)
    result = {
        "status": "planned" if dry_run else "unchanged", "dry_run": dry_run,
        "workspace": str(workspace), "harness": harness, "vault_path": str(vault_path),
        "selection": {"project": project, "personal": personal},
        "python_executable": str(executable), "tested_live": False,
        "advisor": {"choice": advisor, "choice_confirmed": False, "enabled": False,
                    "connector_available": advisor != "none",
                    "setup_status": "disabled" if advisor == "none" else "not_configured"},
        "changes": [], "receipt": None,
        "next_steps": [
            "Reload the chosen client and complete its native workspace trust and MCP approvals. Inspect its server list and tool schemas.",
            "Ask short onboarding questions, save approved answers as source-linked notes, create the requested task, and read the notes and task back.",
            "Core memory is local. Optional Jev/Laya shadow assessment is available through the assess CLI with separate configuration; a recorded choice does not enable billing or a provider. Follow docs/PROVIDERS.md.",
        ],
    }
    changed = []
    for path, before, data in plans:
        differs = before is None or before[0] != data
        change = {"path": str(path), "status": "planned" if differs else "unchanged", "sha256": _digest(data), "backup": None, "readback_verified": False}
        result["changes"].append(change)
        if differs:
            changed.append((path, before, data, change))
    if dry_run or not changed:
        for path, before, _ in plans:
            _ensure_snapshot(path, before)
        if not dry_run:
            for change in result["changes"]:
                change["readback_verified"] = True
        return result
    state = _absolute(_state_root(), "setup backup state")
    if _overlaps(state, workspace) or _overlaps(state, vault_path):
        raise VaultError("unsafe_path", "Setup backup state must be outside the workspace and vault.")
    # Detect a stale plan before creating even the local backup directory.
    for path, before, _ in plans:
        _ensure_snapshot(path, before)
    transaction = state / uuid.uuid4().hex
    state_created = []
    created = []
    applied = []
    receipt = transaction / "receipt.json"
    result["receipt"] = str(receipt)
    try:
        _mkdirs(transaction, state_created)
        for index, (path, before, data, change) in enumerate(changed):
            if before is not None:
                backup = transaction / f"{index}.before"
                _atomic_write(backup, before[0])
                if backup.read_bytes() != before[0]:
                    raise OSError("Backup readback failed")
                change["backup"] = str(backup)
        result["status"] = "applying"
        _receipt(receipt, result)
        for path, before, data, change in changed:
            # Recheck every planned input before each write, including the
            # unchanged skill/config, so stale owner files are never adopted.
            for planned, snapshot, _ in plans:
                if not any(done[0] == planned for done in applied):
                    _ensure_snapshot(planned, snapshot)
            _mkdirs(path.parent, created)
            mode = stat.S_IMODE(before[1][-1]) if before is not None else 0o600
            applied.append((path, before, data, mode))
            _atomic_write(path, data, expected=before, mode=mode)
            _no_links(path)
            if path.read_bytes() != data:
                raise OSError("Installed file readback failed")
            change.update(status="written", readback_verified=True)
        for path, _, data in plans:
            current = _snapshot(path)
            if current is None or current[0] != data:
                raise VaultError("concurrent_change", "A setup target changed before final readback.")
        for change in result["changes"]:
            change["readback_verified"] = True
        result["status"] = "configured"
        _receipt(receipt, result)
        return result
    except (OSError, VaultError) as error:
        failures = []
        for path, before, data, mode in reversed(applied):
            try:
                current = _snapshot(path)
                if current == before:
                    continue  # Publication failed before changing this file.
                if current is None or current[0] != data:
                    raise VaultError("concurrent_change", "Owner edit prevents rollback.")
                if before is None:
                    _ensure_snapshot(path, current)
                    path.unlink()
                else:
                    _atomic_write(path, before[0], expected=current, mode=mode)
                restored = _snapshot(path)
                if (before is None and restored is not None) or (before is not None and (restored is None or restored[0] != before[0])):
                    raise OSError("Rollback readback failed")
            except (OSError, VaultError):
                failures.append(str(path))
        for directory in reversed(created):
            try:
                _no_links(directory)
                directory.rmdir()
            except (OSError, VaultError):
                # Nonempty directories may contain a concurrent owner file.
                pass
        result["status"] = "rollback_failed" if failures else "rolled_back"
        result["rollback_failures"] = failures
        try:
            if transaction.is_dir():
                _receipt(receipt, result)
        except (OSError, VaultError):
            failures.append(str(receipt))
        failure = VaultError("rollback_failed" if failures else getattr(error, "code", "setup_failed"), "Workspace setup failed; inspect the local rollback evidence before retrying.")
        failure.evidence = {"rolled_back": not failures, "receipt": str(receipt) if receipt.exists() else None, "rollback_failures": failures, "changes": result["changes"]}
        raise failure from None
