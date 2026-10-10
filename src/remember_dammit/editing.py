"""Explicit owner-local Markdown working copies of immutable vault revisions.

Manifests and plans are review data, not signed capabilities. Authority always
comes from caller selection and canonical revisions. Apply is a sequence of
atomic corrections, never an all-or-none transaction or an editor refresh.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid

import yaml

from . import retrieval
from .errors import VaultError
from .exporting import _markdown_label
from .locking import writer_lock
from .storage import _canonical, _digest

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 1000
MAX_PLAN_BYTES = 4 * 1024 * 1024
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_ACTOR = "human-editor"


def _json(value, limit=MAX_PLAN_BYTES):
    try:
        result = _canonical(value)
        if len(result) > limit:
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise VaultError("invalid_input", "Editing metadata or plan is invalid or exceeds its byte limit.") from None


def _selection(project, personal):
    retrieval._selection(project, personal, "private")
    return {"project": project, "personal": personal}


def _linked(path):
    junction = getattr(path, "is_junction", None)
    return (path.is_symlink() or (callable(junction) and junction()) or
            (path.exists() and bool(getattr(path.lstat(), "st_file_attributes", 0) &
                                   getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))))


def _safe_path(path):
    try:
        if any(_linked(part) for part in (path, *path.parents)):
            raise VaultError("invalid_workspace", "Working-copy paths cannot traverse links, junctions, or reparse points.")
    except OSError:
        raise VaultError("invalid_workspace", "Working-copy path became unavailable.") from None


def _directory(vault, value, *, new=False):
    try:
        raw = os.fspath(value)
        if not isinstance(raw, str) or not raw.strip() or "\0" in raw:
            raise ValueError
        path = Path(raw).absolute()
        _safe_path(path)
        resolved = path.resolve()
        for forbidden in (vault.root.resolve(), vault.root.resolve().parent / ".remember-dammit-locks"):
            if resolved.is_relative_to(forbidden) or forbidden.is_relative_to(resolved):
                raise VaultError("invalid_workspace", "Working copies must be separate from the canonical vault and writer locks.")
        if new:
            if path.exists():
                raise VaultError("destination_exists", "Working-copy destination must not already exist.")
            if not path.parent.is_dir():
                raise ValueError
        elif not path.is_dir():
            raise ValueError
        return resolved
    except (ValueError, TypeError, OSError):
        raise VaultError("invalid_workspace", "Specify an available separate working-copy directory.") from None


def _read(path, limit=MAX_FILE_BYTES):
    """Bound reads and reject nonregular files or changing file identities."""
    try:
        _safe_path(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise VaultError("invalid_workspace", "Working-copy inputs must be bounded regular files with one link.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read(limit + 1)
            after_open = os.fstat(handle.fileno())
        _safe_path(path)
        after = path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_nlink)
        if (len(data) > limit or identity(before) != identity(opened) or
                identity(before) != identity(after_open) or identity(before) != identity(after)):
            raise VaultError("files_changed", "A working-copy file changed while being read.")
        return data
    except OSError:
        raise VaultError("invalid_workspace", "A working-copy file could not be safely read.") from None


def _filename(record, writable):
    slug = re.sub(r"[^a-z0-9]+", "-", record["title"].casefold()).strip("-")[:60] or "note"
    return ("notes/" if writable else "context/") + slug + "-" + _digest(record["id"].encode()) + ".md"


def _note(record):
    metadata = {"rd_schema": 1, "rd_id": record["id"], "rd_base_revision": record["revision"], "title": record["title"]}
    return ("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + record["body"]).encode("utf-8")


def _home(records, entries):
    paths = {item["id"]: item["path"] for item in entries}
    writable = {item["id"]: item["writable"] for item in entries}
    lines = ["# Remember, Dammit — working notes", "", "Edit title and body only in writable notes.",
             "Context and this Home page are read-only. Preview changes before applying.",
             "Missing notes do not delete memory; new files are skipped.",
             "Apply creates immutable successors. Open a new folder for your next editing session.", "", "## Notes", ""]
    for identifier in sorted(records):
        record = records[identifier]
        lines.append(f"- [{_markdown_label(record['title'])}]({paths[identifier]}) — {'writable' if writable[identifier] else 'read-only context'}")
        for sid in record["sources"]:
            if sid in records:
                lines.append(f"  - Source: [{_markdown_label(records[sid]['title'])}]({paths[sid]})")
        for dependent in sorted(records):
            if identifier in records[dependent]["sources"]:
                lines.append(f"  - Backlink: [{_markdown_label(records[dependent]['title'])}]({paths[dependent]})")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _view(data, selection):
    grants = data["grants"].get(selection["project"], set()) if selection["project"] else set()
    permitted = [record for record in data["current"].values()
                 if retrieval._eligible(record, selection["project"], selection["personal"], "private", grants)]
    candidates, _ = retrieval._candidates(retrieval._source_safe(permitted), False)
    return {record["id"]: record for record in candidates}


def _source_admitted(data, selection):
    """Historical bases may be checked, but every cited dependency must be live."""
    grants = data["grants"].get(selection["project"], set()) if selection["project"] else set()
    return retrieval._source_safe([record for record in data["current"].values()
        if retrieval._eligible(record, selection["project"], selection["personal"], "private", grants)])


def _source_closure(identifier, records):
    seen, pending = set(), list(records[identifier]["sources"])
    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        if source in records:
            pending.extend(records[source]["sources"])
    return seen


def _scope(selection):
    return "personal" if selection["personal"] else "project:" + selection["project"]


def open_editing(vault, new_destination, *, project=None, personal=False):
    """Publish a new bounded working folder; failed opens remain incomplete."""
    selection = _selection(project, personal)
    directory = _directory(vault, new_destination, new=True)
    data = vault._load()
    records = _view(data, selection)
    if len(records) > MAX_FILES - 4:
        raise VaultError("input_limit", "Selected view exceeds the working-copy file limit.")
    entries, payloads = [], {}
    for identifier in sorted(records):
        record = records[identifier]
        writable = record["scope"] == _scope(selection)
        payload = _note(record)
        if len(payload) > MAX_FILE_BYTES:
            raise VaultError("input_limit", "A selected note exceeds the working-copy byte limit.")
        entry = {"id": identifier, "base_revision": record["revision"], "path": _filename(record, writable),
                 "writable": writable, "sha256": _digest(payload)}
        entries.append(entry)
        payloads[entry["path"]] = payload
    manifest = {"schema": 1, "workspace_id": uuid.uuid4().hex, "vault_id": vault.vault_id,
                "selection": selection, "opened_snapshot": data["snapshot"], "notes": entries}
    manifest["manifest_digest"] = _digest(_json(manifest, MAX_FILE_BYTES))
    payloads["manifest.json"] = _json(manifest, MAX_FILE_BYTES)
    payloads["Home.md"] = _home(records, entries)
    payloads["COMPLETE.md"] = ("# Completed working copy\n\nManifest: " + manifest["manifest_digest"] + "\n").encode()
    if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES or any(len(value) > MAX_FILE_BYTES for value in payloads.values()):
        raise VaultError("input_limit", "Selected working copy exceeds its input limits.")
    try:
        directory.mkdir()
        (directory / "INCOMPLETE.md").write_bytes(b"# INCOMPLETE WORKING COPY\nDo not preview or apply this folder.\n")
        identity = directory.stat().st_dev, directory.stat().st_ino
        for name in ("notes", "context"):
            (directory / name).mkdir()
        for relative, payload in payloads.items():
            _safe_path(directory / relative)
            if (directory.stat().st_dev, directory.stat().st_ino) != identity:
                raise VaultError("invalid_workspace", "Working-copy directory changed during publication.")
            with (directory / relative).open("xb") as handle:
                handle.write(payload)
        with writer_lock(vault.root):
            if vault._load()["snapshot"] != data["snapshot"]:
                raise VaultError("source_changed", "Vault or policy changed during open; the working copy is incomplete.")
            _safe_path(directory)
            if (directory.stat().st_dev, directory.stat().st_ino) != identity:
                raise VaultError("invalid_workspace", "Working-copy directory changed during publication.")
            for relative, payload in payloads.items():
                if _read(directory / relative) != payload:
                    raise VaultError("files_changed", "Working-copy output changed during open; the folder remains incomplete.")
            if _read(directory / "INCOMPLETE.md") != b"# INCOMPLETE WORKING COPY\nDo not preview or apply this folder.\n":
                raise VaultError("invalid_workspace", "Incomplete marker changed during publication.")
            (directory / "INCOMPLETE.md").unlink()
    except FileExistsError:
        raise VaultError("destination_exists", "Working-copy output already exists; incomplete output is preserved.") from None
    except OSError:
        raise VaultError("editing_open_failed", "Working-copy publication failed; incomplete output is preserved.") from None
    writable_count = sum(item["writable"] for item in entries)
    return {"status": "complete", "path": str(directory), "home": str(directory / "Home.md"),
            "manifest": str(directory / "manifest.json"), "records": len(entries),
            "writable": writable_count, "readonly": len(entries) - writable_count}


def _manifest(vault, directory, selection, data):
    try:
        if (directory / "INCOMPLETE.md").exists():
            raise ValueError
        raw = _read(directory / "manifest.json")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        manifest = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(manifest, dict) or set(manifest) != {"schema", "workspace_id", "vault_id", "selection", "opened_snapshot", "notes", "manifest_digest"}
                or type(manifest["schema"]) is not int or manifest["schema"] != 1
                or manifest["vault_id"] != vault.vault_id or manifest["selection"] != selection
                or not isinstance(manifest["workspace_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", manifest["workspace_id"])
                or not isinstance(manifest["opened_snapshot"], str) or not _HEX.fullmatch(manifest["opened_snapshot"])
                or not isinstance(manifest["notes"], list) or len(manifest["notes"]) > MAX_FILES - 4):
            raise ValueError
        unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
        if manifest["manifest_digest"] != _digest(_json(unsigned, MAX_FILE_BYTES)):
            raise ValueError
        bases, paths = {}, set()
        for entry in manifest["notes"]:
            if (not isinstance(entry, dict) or set(entry) != {"id", "base_revision", "path", "writable", "sha256"}
                    or not isinstance(entry["id"], str) or entry["id"] in bases
                    or not isinstance(entry["path"], str) or entry["path"].casefold() in paths
                    or type(entry["writable"]) is not bool):
                raise ValueError
            base = data["records"].get(entry["id"])
            if base is None or base["revision"] != entry["base_revision"] or base["state"] != "active":
                raise ValueError
            writable = base["scope"] == _scope(selection)
            if entry["writable"] != writable or entry["path"] != _filename(base, writable) or entry["sha256"] != _digest(_note(base)):
                raise ValueError
            # Scope authorization is canonical even for historical retry bases.
            grants = data["grants"].get(selection["project"], set()) if selection["project"] else set()
            if not retrieval._eligible(base, selection["project"], selection["personal"], "private", grants):
                raise VaultError("scope_changed", "A working-copy record is no longer permitted in the explicit selection.")
            paths.add(entry["path"].casefold())
            bases[entry["id"]] = base
        return raw, manifest, bases
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise VaultError("invalid_workspace", "Working-copy manifest is incomplete, changed, or invalid for this selection.") from None


def _parse(raw):
    try:
        text = raw.decode("utf-8-sig")
        start = re.match(r"---\r?\n", text)
        if start is None:
            raise ValueError
        end = re.search(r"\r?\n---\r?\n", text[start.end():])
        if end is None:
            raise ValueError
        frontmatter = text[start.end():start.end() + end.start()]
        body = text[start.end() + end.end():]
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(frontmatter)):
            raise ValueError
        node = yaml.compose(frontmatter)
        if not isinstance(node, yaml.nodes.MappingNode) or len(node.value) != 4:
            raise ValueError
        values = {}
        for key, value in node.value:
            if (not isinstance(key, yaml.nodes.ScalarNode) or key.tag != "tag:yaml.org,2002:str" or key.value in values
                    or not isinstance(value, yaml.nodes.ScalarNode)):
                raise ValueError
            if key.value == "rd_schema":
                if value.tag != "tag:yaml.org,2002:int" or value.value != "1":
                    raise ValueError
                values[key.value] = 1
            else:
                if value.tag != "tag:yaml.org,2002:str":
                    raise ValueError
                values[key.value] = value.value
        if set(values) != {"rd_schema", "rd_id", "rd_base_revision", "title"} or not values["title"].strip() or not body.strip():
            raise ValueError
        return values, body
    except (ValueError, UnicodeError, yaml.YAMLError, RecursionError):
        raise VaultError("invalid_note", "Note frontmatter must contain only locked identity and an editable nonempty title/body.") from None


def _scan(directory):
    """One level of managed directories; arbitrary subtrees are never visited."""
    found, count, names = {}, 0, set()
    for folder in (directory, directory / "notes", directory / "context"):
        _safe_path(folder)
        if not folder.is_dir():
            raise VaultError("invalid_workspace", "Working-copy managed directories are missing.")
        with os.scandir(folder) as iterator:
            for entry in iterator:
                count += 1
                if count > MAX_FILES + 2:
                    raise VaultError("input_limit", "Working copy exceeds its directory-entry limit.")
                path = Path(entry.path)
                _safe_path(path)
                if path == directory / "notes" or path == directory / "context":
                    continue
                relative = path.relative_to(directory).as_posix()
                normalized = unicodedata.normalize("NFC", relative).casefold()
                if normalized in names:
                    raise VaultError("invalid_workspace", "Working-copy paths have a case or Unicode collision.")
                names.add(normalized)
                if entry.is_dir(follow_symlinks=False):
                    found[relative] = None
                else:
                    found[relative] = path
    return found


def _request(change):
    return {"action": "correct", "record_id": change["id"], "expected_revision": change["base_revision"],
            "title": change["title"], "body": change["body"], "actor": _ACTOR, "aliases": None, "sources": None}


def _receipt(data, change):
    op = data["operations"].get(change["operation_id"])
    if op is None:
        return None
    if op["action"] != "correct" or op["request_digest"] != _digest(_json(_request(change))):
        raise VaultError("operation_conflict", "An editing operation ID was admitted with another request.")
    record = data["records"][op["result"]["id"]]
    if record["supersedes"] != change["id"]:
        raise VaultError("operation_conflict", "Editing operation receipt has a different predecessor.")
    return record


def _inspect(vault, workspace, selection, data, *, allow_replays=False):
    directory = _directory(vault, workspace)
    raw_manifest, manifest, bases = _manifest(vault, directory, selection, data)
    found = _scan(directory)
    files, skipped, conflicts, changes = [], [], [], []
    total = 0
    expected = {entry["path"]: entry for entry in manifest["notes"]}
    admitted_sources = _source_admitted(data, selection)
    readonly = {"Home.md": _home(bases, manifest["notes"]),
                "COMPLETE.md": ("# Completed working copy\n\nManifest: " + manifest["manifest_digest"] + "\n").encode()}
    required = {"manifest.json", *readonly}
    for missing in sorted(required - found.keys()):
        conflicts.append({"code": "missing_control", "path": missing})
    for relative in sorted(found):
        path = found[relative]
        if path is None:
            files.append({"path": relative, "sha256": None})
            skipped.append({"code": "unexpected_directory", "path": relative})
            continue
        raw = raw_manifest if relative == "manifest.json" else _read(path)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise VaultError("input_limit", "Working-copy reads exceed the total byte limit.")
        digest = _digest(raw)
        files.append({"path": relative, "sha256": digest})
        if relative in readonly:
            if raw != readonly[relative]:
                conflicts.append({"code": "readonly_changed", "path": relative})
        elif relative in expected:
            entry = expected[relative]
            base = bases[entry["id"]]
            if not entry["writable"]:
                if raw != _note(base):
                    conflicts.append({"code": "readonly_changed", "path": relative})
                continue
            try:
                metadata, body = _parse(raw)
                if metadata["rd_id"] != entry["id"] or metadata["rd_base_revision"] != entry["base_revision"]:
                    raise VaultError("identity_changed", "Locked record identity changed.")
                if metadata["title"] == base["title"] and body == base["body"]:
                    continue
                change = {"id": entry["id"], "path": relative, "base_revision": base["revision"], "sha256": digest,
                          "title": metadata["title"], "body": body}
                change["operation_id"] = "edit-" + _digest(_json({"schema": 1, "vault_id": vault.vault_id,
                                                                "workspace_id": manifest["workspace_id"], "request": _request(change)}))
                if base["id"] not in admitted_sources and not (allow_replays and _receipt(data, change) is not None):
                    raise VaultError("source_or_scope_changed", "A dependent note is withheld because its canonical sources are not currently eligible.")
                change["before"] = {"title": base["title"], "body": base["body"]}
                changes.append(change)
            except VaultError as exc:
                conflicts.append({"code": exc.code, "path": relative})
        elif relative != "manifest.json":
            skipped.append({"code": "unexpected_file", "path": relative})
    for relative in sorted(expected.keys() - found.keys()):
        files.append({"path": relative, "sha256": None})
        skipped.append({"code": "missing_note", "path": relative})
    changes.sort(key=lambda item: item["id"])
    changed = {item["id"] for item in changes}
    for change in changes:
        if changed.intersection(_source_closure(change["id"], data["records"])):
            conflicts.append({"code": "source_dependent_batch", "id": change["id"]})
    visible = _view(data, selection)
    warnings = []
    for change in changes:
        dependents = [{"id": item["id"], "title": item["title"]} for identifier, item in sorted(visible.items())
                      if change["id"] in _source_closure(identifier, visible)]
        if dependents:
            warnings.append({"code": "dependent_recall_impact", "id": change["id"], "dependents": dependents,
                             "message": "Correcting a cited ID leaves existing citations on its predecessor and may withhold dependent recall. Dependencies outside this view may also be affected."})
    return {"schema": 1, "vault_id": vault.vault_id, "selection": selection, "manifest_sha256": _digest(raw_manifest),
            "files": sorted(files, key=lambda item: item["path"]), "changes": changes,
            "conflicts": conflicts, "skipped": skipped, "warnings": warnings}, manifest, bases


def _preflight(data, selection, manifest, changes):
    visible = _view(data, selection)
    by_id = {item["id"]: item for item in changes}
    conflicts = []
    for entry in manifest["notes"]:
        change = by_id.get(entry["id"])
        if change is None:
            continue  # Unedited notes are context, not correction targets.
        if _receipt(data, change) is not None:
            continue  # A journal receipt proves historical admission, not current state.
        current = data["current"].get(entry["id"])
        if current is None or current["revision"] != entry["base_revision"] or current["state"] != "active":
            conflicts.append({"code": "stale_revision", "id": entry["id"]})
        elif entry["id"] not in visible:
            conflicts.append({"code": "source_or_scope_changed", "id": entry["id"]})
    return conflicts


def _impact_preflight(data, changes, reviewed_warnings, current_warnings):
    """Pending corrections may only reduce the impact that was reviewed."""
    def impacts(warnings):
        if not isinstance(warnings, list):
            raise VaultError("invalid_plan", "Reviewed impact warnings must be a list.")
        result = {}
        for warning in warnings:
            if (not isinstance(warning, dict) or set(warning) != {"code", "id", "dependents", "message"}
                    or warning["code"] != "dependent_recall_impact" or not isinstance(warning["id"], str)
                    or warning["id"] in result or not isinstance(warning["dependents"], list)
                    or not isinstance(warning["message"], str)):
                raise VaultError("invalid_plan", "Reviewed impact warning is invalid.")
            dependents, identities = set(), set()
            for dependent in warning["dependents"]:
                if (not isinstance(dependent, dict) or set(dependent) != {"id", "title"}
                        or not isinstance(dependent["id"], str) or not isinstance(dependent["title"], str)
                        or dependent["id"] in identities):
                    raise VaultError("invalid_plan", "Reviewed dependent impact is invalid.")
                identities.add(dependent["id"])
                dependents.add((dependent["id"], dependent["title"]))
            result[warning["id"]] = dependents
        return result
    reviewed, current = impacts(reviewed_warnings), impacts(current_warnings)
    for change in changes:
        if _receipt(data, change) is not None:
            continue  # Historical admission must not be inferred to have a new impact.
        if not current.get(change["id"], set()).issubset(reviewed.get(change["id"], set())):
            raise VaultError("impact_changed", "A pending correction has new or changed visible dependent impact; prepare a fresh preview.")


def plan_edits(vault, workspace, *, project=None, personal=False):
    """Read actual bounded bytes and canonical bases, returning a complete preview."""
    selection = _selection(project, personal)
    data = vault._load()
    try:
        plan, manifest, _ = _inspect(vault, workspace, selection, data)
    except OSError:
        raise VaultError("invalid_workspace", "Working-copy inputs became unavailable during preview.") from None
    plan["conflicts"].extend(_preflight(data, selection, manifest, plan["changes"]))
    plan["status"] = "conflict" if plan["conflicts"] else "ready"
    if vault._load()["snapshot"] != data["snapshot"]:
        raise VaultError("source_changed", "Vault or policy changed during preview; retry.")
    plan["plan_digest"] = _digest(_json(plan))
    _json(plan)
    return plan


def _failure(completed, code, message, *, index=None):
    return {"status": "partial" if completed or index is not None else "conflict", "atomic": False,
            "completed": completed, "successors": {item["id"]: item["successor_id"] for item in completed},
            "failed_index": index, "error": {"code": code, "message": message},
            "retry_same_plan": bool(completed) or index is not None, "requires_new_workspace": True}


def apply_edits(vault, workspace, plan, *, project=None, personal=False):
    """Apply reviewed bytes with whole-set preflight, exact receipts, and per-write freshness.

    Input plans do not authorize writes. They are reconstructed from unchanged
    files and canonical records. Files and manifests are never refreshed here.
    """
    selection = _selection(project, personal)
    completed = []
    try:
        _json(plan)
        keys = {"schema", "vault_id", "selection", "manifest_sha256", "files", "changes", "conflicts", "skipped", "warnings", "status", "plan_digest"}
        if not isinstance(plan, dict) or set(plan) != keys or plan["selection"] != selection or plan["vault_id"] != vault.vault_id:
            raise VaultError("invalid_plan", "Plan does not match the explicit vault and selection.")
        unsigned = {key: value for key, value in plan.items() if key != "plan_digest"}
        if plan["plan_digest"] != _digest(_json(unsigned)) or plan["status"] != "ready" or plan["conflicts"]:
            raise VaultError("invalid_plan", "Apply requires an unchanged conflict-free reviewed plan.")
        data = vault._load()
        actual, manifest, _ = _inspect(vault, workspace, selection, data, allow_replays=True)
        for key in ("schema", "vault_id", "selection", "manifest_sha256", "files", "changes", "skipped"):
            if actual[key] != plan[key]:
                raise VaultError("files_changed", "Working-copy bytes or planned requests changed after preview.")
        if actual["conflicts"] or _preflight(data, selection, manifest, actual["changes"]):
            raise VaultError("editing_conflict", "A file, target head, scope, or source is no longer eligible; no pending changes were applied.")
        _impact_preflight(data, actual["changes"], plan["warnings"], actual["warnings"])
        # Check every reviewed file again after the potentially long target preflight.
        refreshed, _, _ = _inspect(vault, workspace, selection, data, allow_replays=True)
        if refreshed["files"] != actual["files"] or refreshed["changes"] != actual["changes"]:
            raise VaultError("files_changed", "Working-copy bytes changed during apply preflight.")
    except VaultError as exc:
        return _failure(completed, exc.code, exc.message)
    except OSError:
        return _failure(completed, "invalid_workspace", "Working-copy inputs became unavailable during apply preflight.")
    for index, change in enumerate(actual["changes"]):
        try:
            data = vault._load()
            refreshed, _, _ = _inspect(vault, workspace, selection, data, allow_replays=True)
            if refreshed["files"] != actual["files"] or refreshed["changes"] != actual["changes"] or refreshed["conflicts"]:
                raise VaultError("files_changed", "Working-copy files changed during apply; remaining writes were stopped.")
            replay = _receipt(data, change)
            if replay is None:
                if _preflight(data, selection, manifest, actual["changes"]):
                    raise VaultError("editing_conflict", "A remaining head, scope, or source changed during apply.")
                _impact_preflight(data, actual["changes"], plan["warnings"], refreshed["warnings"])
                record = vault.correct(change["id"], expected_revision=change["base_revision"],
                                       title=change["title"], body=change["body"], actor=_ACTOR,
                                       operation_id=change["operation_id"], aliases=None, sources=None,
                                       expected_snapshot=data["snapshot"])
            else:
                record = replay
            completed.append({"id": change["id"], "successor_id": record["id"], "revision": record["revision"],
                              "replayed": replay is not None, "admission": "historical" if replay is not None else "committed"})
        except VaultError as exc:
            return _failure(completed, exc.code, exc.message, index=index)
        except OSError:
            return _failure(completed, "storage_error", "A correction could not be persisted; retry the same plan to resolve admission.", index=index)
    return {"status": "complete", "atomic": False, "completed": completed,
            "successors": {item["id"]: item["successor_id"] for item in completed},
            "retry_same_plan": True, "requires_new_workspace": True}
