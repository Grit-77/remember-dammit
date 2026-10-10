"""Explicit owner-local Markdown snapshots; exported edits never write back."""

from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path

import yaml

from .errors import VaultError
from .locking import writer_lock
from . import retrieval


_LABEL = "Snapshot: edits do not update the live vault."
_METADATA = ("id", "revision", "kind", "scope", "state", "title", "aliases",
             "evidence", "disclosure", "remote_allowed", "actor", "created_at")


def _is_link(path):
    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(junction) and junction())


def _guard(directory, vault_root, identity=None):
    """Reject links before resolution, including Windows directory junctions."""
    try:
        if any(_is_link(path) for path in (directory, *directory.parents)):
            raise VaultError("invalid_destination", "Snapshot paths cannot contain symlinks or junctions.")
        if directory.resolve().is_relative_to(vault_root):
            raise VaultError("invalid_destination", "Snapshots must be outside the canonical vault.")
        if identity is not None:
            stat = directory.stat()
            if (stat.st_dev, stat.st_ino) != identity:
                raise VaultError("invalid_destination", "Snapshot directory changed during export.")
    except OSError:
        raise VaultError("invalid_destination", "Snapshot path is unavailable.") from None


def _destination(destination, vault_root):
    try:
        value = os.fspath(destination)
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError
        path = Path(value).absolute()
    except (TypeError, ValueError, OSError):
        raise VaultError("invalid_destination", "Specify a new snapshot directory.") from None
    _guard(path, vault_root)
    path = path.resolve()
    if path.exists():
        raise VaultError("destination_exists", "Snapshot destination must not already exist.")
    if not path.parent.is_dir():
        raise VaultError("invalid_destination", "Snapshot parent directory must already exist.")
    return path


def _write_new(directory, relative, text, vault_root, identity):
    _guard(directory, vault_root, identity)
    target = directory / relative
    if any(_is_link(path) for path in (target, *target.parents)):
        raise VaultError("invalid_destination", "Snapshot output path changed during export.")
    with target.open("xb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        stat = os.fstat(handle.fileno())
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _markdown_label(value):
    label = html.escape(" ".join(value.split()), quote=False)
    for character in "\\`*_{}[]()#!|":
        label = label.replace(character, "\\" + character)
    return label


def _note(record, records, filenames, snapshot):
    metadata = {field: record[field] for field in _METADATA}
    metadata.update(snapshot=snapshot, snapshot_only=True)
    metadata["sources"] = [source for source in record.get("sources", []) if source in records]
    metadata["source_files"] = {source: Path(filenames[source]).name for source in metadata["sources"]}
    predecessor = record.get("supersedes")
    metadata["supersedes"] = predecessor if predecessor in records else None
    successors = sorted(item["id"] for item in records.values() if item.get("supersedes") == record["id"])
    metadata["successors"] = successors
    links = ["[Home](../Home.md)"]
    if metadata["sources"]:
        links += ["", "## Sources"]
        links += [f"- [{_markdown_label(records[source]['title'])}]({Path(filenames[source]).name})" for source in metadata["sources"]]
    if metadata["supersedes"] or successors:
        links += ["", "## History"]
        if metadata["supersedes"]:
            links.append(f"- Predecessor: [{_markdown_label(records[predecessor]['title'])}]({Path(filenames[predecessor]).name})")
        links += [f"- Successor: [{_markdown_label(records[successor]['title'])}]({Path(filenames[successor]).name})" for successor in successors]
    return (
        "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n\n"
        f"> **{_LABEL}**\n\n"
        f"# {_markdown_label(record['title'])}\n\n"
        + "\n".join(links) + "\n\n## Record body\n\n" + record["body"]
    )


def _fresh(vault, snapshot):
    try:
        retrieval._fresh(vault, snapshot)
    except VaultError:
        raise VaultError("source_changed", "Vault content or sharing policy changed during export; snapshot is incomplete.") from None


def export_snapshot(vault, destination, *, project=None, personal=False, include_history=False) -> dict:
    """Export permitted records into a new directory with an existing parent.

    The audience is the local owner (private), exactly as default retrieval.
    Source filtering is transitive; unavailable or inactive dependencies withhold
    the whole dependent record. History is opt-in. Existing paths are never
    overwritten. Failures after creation leave INCOMPLETE.md and no success result.
    Completion is published under the participating writer lock; later revocation
    cannot retract previously exported bytes. The vault parent must be writable
    for the existing local lock namespace.
    """
    retrieval._selection(project, personal, "private")
    if not isinstance(include_history, bool):
        raise VaultError("invalid_input", "include_history must be boolean.")
    vault_root = vault.root.resolve()
    directory = _destination(destination, vault_root)
    snapshot, all_records, grants = retrieval._snapshot(vault, project)
    permitted = [record for record in all_records if retrieval._eligible(record, project, personal, "private", grants)]
    source_safe = retrieval._source_safe(permitted)
    candidates, _ = retrieval._candidates(source_safe, include_history)
    records = {record["id"]: record for record in candidates}
    filenames = {identifier: "notes/" + hashlib.sha256(identifier.encode("utf-8")).hexdigest() + ".md"
                 for identifier in records}
    try:
        _guard(directory, vault_root)
        directory.mkdir()
    except FileExistsError:
        raise VaultError("destination_exists", "Snapshot destination must not already exist.") from None
    except OSError:
        raise VaultError("export_failed", "Snapshot directory could not be created.") from None
    stat = directory.stat()
    identity = (stat.st_dev, stat.st_ino)
    try:
        marker_identity = _write_new(directory, "INCOMPLETE.md", (
            "# INCOMPLETE SNAPSHOT\n\n" + _LABEL + "\n\n"
            "If this file exists, this export is incomplete, even if COMPLETE.md is present.\n"
            "Do not treat its partial records as a completed snapshot.\n"
        ), vault_root, identity)
        _guard(directory, vault_root, identity)
        (directory / "notes").mkdir()
        for identifier in sorted(records):
            _write_new(directory, filenames[identifier], _note(records[identifier], records, filenames, snapshot), vault_root, identity)
        home = ["# Remember, Dammit — snapshot", "", f"> **{_LABEL}**", "",
                "This folder is an owner-local export, not a synchronized vault.",
                "INCOMPLETE.md takes precedence: while it exists, the export is incomplete.",
                "A completed export has COMPLETE.md and no INCOMPLETE.md.", "",
                f"Snapshot: `{snapshot}`", f"Selection: {'personal' if personal else 'project:' + project}",
                f"History included: {str(include_history).lower()}", "", "## Records", ""]
        home.extend(f"- [{_markdown_label(record['title'])}]({filenames[identifier]}) — {record['kind']} / {record['state']}"
                    for identifier, record in sorted(records.items()))
        if not records:
            home.append("No permitted records with disclosable active source dependencies.")
        _write_new(directory, "Home.md", "\n".join(home) + "\n", vault_root, identity)
        _fresh(vault, snapshot)
        _write_new(directory, "COMPLETE.md", f"# Completed snapshot\n\n{_LABEL}\n\nSnapshot: `{snapshot}`\n", vault_root, identity)
        _guard(directory, vault_root, identity)
        # This marker belongs to this newly created export; no user paths are
        # recursively removed and no canonical vault content is changed.
        marker = directory / "INCOMPLETE.md"
        marker_stat = marker.lstat()
        if (_is_link(marker) or
                (marker_stat.st_dev, marker_stat.st_ino, marker_stat.st_size, marker_stat.st_mtime_ns) != marker_identity):
            raise VaultError("export_failed", "Incomplete marker changed; it was preserved and export is incomplete.")
        with writer_lock(vault.root):
            # Use direct path checks here: do not invoke callbacks which might
            # attempt a nested vault write while the native writer lock is held.
            directory_stat = directory.stat()
            if (any(_is_link(path) for path in (directory, *directory.parents)) or
                    (directory_stat.st_dev, directory_stat.st_ino) != identity):
                raise VaultError("invalid_destination", "Snapshot directory changed during finalization.")
            marker_stat = marker.lstat()
            if (_is_link(marker) or
                    (marker_stat.st_dev, marker_stat.st_ino, marker_stat.st_size, marker_stat.st_mtime_ns) != marker_identity):
                raise VaultError("export_failed", "Incomplete marker changed; export remains incomplete.")
            # This is the completion point against cooperating managed writers:
            # none can change records or grants between this check and removal.
            _fresh(vault, snapshot)
            marker.unlink()
    except VaultError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise VaultError("export_failed", "Snapshot write failed; the export is incomplete.") from None
    return {"status": "complete", "path": str(directory), "home": str(directory / "Home.md"),
            "records": len(records), "snapshot": snapshot, "include_history": include_history,
            "omitted_source_dependencies": len(permitted) - len(source_safe)}
