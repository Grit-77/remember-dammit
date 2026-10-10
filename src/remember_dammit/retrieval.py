"""Scope-first lexical passages and model-independent, byte-bounded context.

Search builds an in-memory FTS5 index from the validated, permitted snapshot.
The optional on-disk projection produced by reindex is disposable and is never
read as an authority. This alpha favors fresh source validation over large-vault
performance; it does not perform semantic or cross-language inference.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path

from .errors import VaultError
from .validation import validate_identifier


def encode_packet(packet: dict) -> str:
    return json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _selection(project, personal, audience):
    if bool(project) == bool(personal) or not isinstance(personal, bool):
        raise VaultError("invalid_scope", "Select exactly one project or personal context.")
    if project is not None:
        try:
            validate_identifier(project, "Project ID")
        except VaultError:
            raise VaultError("invalid_scope", "Invalid project identifier.") from None
    if audience not in {"private", "shared", "public"}:
        raise VaultError("invalid_input", "Unknown disclosure audience.")


def _eligible(record, project, personal, audience, grants):
    visible = {"private": {"private", "shared", "public"},
               "shared": {"shared", "public"}, "public": {"public"}}[audience]
    if record.get("disclosure") not in visible:
        return False
    scope = record.get("scope")
    return (scope == "shared" or (personal and scope == "personal") or
            (project and (scope == f"project:{project}" or
                          (scope == "personal" and record.get("id") in grants))))


def visible_record(vault, record, *, project=None, personal=False, audience="private") -> bool:
    """Scope/disclosure check only; historical state is allowed for inspectors."""
    _selection(project, personal, audience)
    grants = vault.grants_for(project) if project else set()
    return bool(_eligible(record, project, personal, audience, grants))


def _snapshot(vault, project=None):
    for _ in range(3):
        before = vault.snapshot_id()
        records = vault.list_records()
        grants = vault.grants_for(project) if project else set()
        if before == vault.snapshot_id():
            return before, records, grants
    raise VaultError("source_changed", "Vault changed while preparing context; retry the request.")


def _fresh(vault, snapshot):
    if vault.snapshot_id() != snapshot:
        raise VaultError("source_changed", "Vault or sharing policy changed before delivery; retry.")


def _normalize(text):
    value = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    return "".join(char for char in value if not unicodedata.combining(char))


def _tokens(query):
    if not isinstance(query, str) or len(query.encode("utf-8")) > 4096:
        raise VaultError("invalid_input", "Query must be text of at most 4096 UTF-8 bytes.")
    return list(dict.fromkeys(re.findall(r"[^\W_]+", _normalize(query))))[:32]


def _passages(body):
    """Return intact paragraphs/heading sections with exact character offsets."""
    boundaries = {0, len(body)}
    boundaries.update(match.start() for match in re.finditer(r"(?m)^#{1,6}\s+", body))
    boundaries.update(match.end() for match in re.finditer(r"\n\s*\n", body))
    ordered = sorted(boundaries)
    for start, end in zip(ordered, ordered[1:]):
        while start < end and body[start].isspace():
            start += 1
        while end > start and body[end - 1].isspace():
            end -= 1
        if start < end:
            yield start, end, body[start:end]


def _ancestor_ids(record, by_id):
    """Walk every visible predecessor, allowing shared DAG ancestors."""
    def parents(item):
        return item.get("supersedes_all") or ([item["supersedes"]] if item.get("supersedes") else [])
    seen = {record["id"]}
    visiting = {record["id"]}
    stack = [(record["id"], iter(sorted(parents(record))))]
    result = []
    while stack:
        try:
            parent_id = next(stack[-1][1])
        except StopIteration:
            visiting.remove(stack.pop()[0])
            continue
        if parent_id in visiting:
            raise VaultError("integrity_error", "Cyclic correction history.")
        if parent_id in seen or parent_id not in by_id:
            continue
        seen.add(parent_id)
        visiting.add(parent_id)
        result.append(parent_id)
        stack.append((parent_id, iter(sorted(parents(by_id[parent_id])))))
    return result


def _source_safe(records):
    """Remove records whose cited dependencies cannot be disclosed as active."""
    by_id = {record["id"]: record for record in records}
    while True:
        blocked = {identifier for identifier, item in by_id.items()
                   if any(source not in by_id or by_id[source]["state"] != "active"
                          for source in item.get("sources", []))}
        if not blocked:
            return by_id
        by_id = {identifier: item for identifier, item in by_id.items() if identifier not in blocked}


def _item(record, passage, by_id, score=0.0, reason="lexical passage match"):
    start, end, text = passage
    return {"id": record["id"], "revision": record["revision"],
            "title": record["title"], "body": text, "scope": record["scope"],
            "kind": record["kind"], "state": record["state"],
            "context_role": "reference_source" if record["kind"] == "source" else "memory",
            "evidence": record["evidence"], "score": round(score, 8), "reason": reason,
            "citation": {"id": record["id"], "revision": record["revision"],
                         "path": record["path"], "start": start, "end": end},
            "sources": [{"id": sid, "revision": by_id[sid]["revision"],
                         "title": by_id[sid]["title"], "path": by_id[sid]["path"]}
                        for sid in record.get("sources", []) if sid in by_id],
            "conflicts_with": []}


def _candidates(by_id, include_history):
    """Shared active/history selection for retrieval and explicit snapshots."""
    obsolete_sources = {source for item in by_id.values() if item["state"] in {"superseded", "retracted"}
                        for source in item.get("sources", [])}
    current_sources = {source for item in by_id.values() if item["state"] == "active"
                       for source in item.get("sources", [])}
    historical_only = {identifier for identifier in obsolete_sources - current_sources
                       if identifier in by_id and by_id[identifier]["kind"] == "source"}
    candidates = [item for item in by_id.values()
                  if include_history or (item["state"] == "active" and item["id"] not in historical_only)]
    return candidates, historical_only


def _rank(records, tokens, include_history):
    if not tokens:
        return [], []
    by_id = _source_safe(records)
    candidates, historical_only = _candidates(by_id, include_history)
    if not candidates:
        return [], []
    passages = {}
    ancestors = {}
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE phrases USING fts5(title, text, inherited, tokenize='unicode61')")
        for record in candidates:
            ancestor_ids = _ancestor_ids(record, by_id)
            ancestors[record["id"]] = ancestor_ids
            inherited = " ".join(by_id[identifier]["title"] + " " + by_id[identifier]["body"] + " " +
                                 " ".join(by_id[identifier].get("aliases", [])) for identifier in ancestor_ids)
            for passage in _passages(record["body"]):
                title = record["title"] + " " + " ".join(record.get("aliases", []))
                cursor = connection.execute("INSERT INTO phrases(title,text,inherited) VALUES (?,?,?)",
                                            (_normalize(title), _normalize(passage[2]), _normalize(inherited)))
                passages[cursor.lastrowid] = (record, passage, bool(inherited))
        query = " OR ".join('"' + token + '"' for token in tokens)
        rows = connection.execute("SELECT rowid, bm25(phrases,3.0,1.0,0.5) AS rank FROM phrases WHERE phrases MATCH ? ORDER BY rank,rowid", (query,)).fetchall()
    except sqlite3.OperationalError as exc:
        raise VaultError("search_unavailable", "SQLite FTS5 is required for local search.") from exc
    finally:
        connection.close()
    chosen = {}
    for rowid, rank in rows:
        record, passage, inherited = passages[rowid]
        if record["id"] not in chosen:
            reason = "lexical passage match; supersession terms considered" if inherited else "lexical passage match"
            chosen[record["id"]] = _item(record, passage, by_id, -rank, reason)

    # A relevant branch must not appear settled merely because its sibling has
    # different words. Preserve all permitted active heads of the same lineage.
    roots = {}
    for record in candidates:
        if record["state"] == "active":
            lineage = ancestors.get(record["id"], [])
            root = record.get("lineage_id") or (lineage[-1] if lineage else record["id"])
            roots.setdefault(root, []).append(record["id"])
    bundles = []
    emitted = set()
    for identifier in list(chosen):
        if identifier in emitted:
            continue
        lineage = ancestors.get(identifier, [])
        root = by_id[identifier].get("lineage_id") or (lineage[-1] if lineage else identifier)
        group = sorted(roots.get(root, [identifier]))
        if include_history or len(group) < 2:
            group = [identifier]
        bundle = []
        for sibling in group:
            item = chosen.get(sibling)
            if item is None:
                record = by_id[sibling]
                item = _item(record, next(_passages(record["body"])), by_id,
                             reason="required conflicting correction")
            if len(group) > 1:
                item["conflicts_with"] = [other for other in group if other != sibling]
            bundle.append(item)
            emitted.add(sibling)
        bundles.append(bundle)
    warnings = ["unresolved_correction_branches"] if any(len(b) > 1 for b in bundles) else []
    if historical_only and not include_history:
        warnings.append("historical_only_sources_excluded_use_history_to_inspect")
    return bundles, warnings


def _request(vault, query, project, personal, audience, include_history):
    _selection(project, personal, audience)
    tokens = _tokens(query)
    snapshot, records, grants = _snapshot(vault, project)
    permitted = [record for record in records if _eligible(record, project, personal, audience, grants)]
    bundles, warnings = _rank(permitted, tokens, include_history)
    return snapshot, bundles, warnings


def _packet(vault, query, snapshot, warnings, matched):
    return {"schema_version": 1, "vault_id": vault.vault_id, "snapshot": snapshot,
            "query": query, "provider": "off", "status": "ok" if matched else "no_results",
            "matched_count": matched, "records": [], "warnings": warnings,
            "omitted": {"limit": 0, "budget": 0}}


def search(vault, query, *, project=None, personal=False, limit=10, include_history=False, audience="private"):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise VaultError("invalid_input", "Limit must be an integer between 1 and 100.")
    snapshot, bundles, warnings = _request(vault, query, project, personal, audience, include_history)
    packet = _packet(vault, query, snapshot, warnings, sum(map(len, bundles)))
    for bundle in bundles:
        if len(packet["records"]) + len(bundle) <= limit:
            packet["records"].extend(bundle)
        else:
            packet["omitted"]["limit"] += len(bundle)
    if bundles and not packet["records"]:
        packet["status"] = "omitted"
    _fresh(vault, snapshot)
    return packet


def context(vault, query, *, project=None, personal=False, budget_bytes=8000, audience="private"):
    if not isinstance(budget_bytes, int) or isinstance(budget_bytes, bool) or not 1 <= budget_bytes <= 1_000_000:
        raise VaultError("invalid_input", "Budget must be an integer from 1 to 1000000 bytes.")
    snapshot, bundles, warnings = _request(vault, query, project, personal, audience, False)
    count = sum(map(len, bundles))
    packet = _packet(vault, query, snapshot, warnings, count)
    packet["budget_bytes"] = budget_bytes
    packet["omitted"]["budget"] = count
    if len(encode_packet(packet).encode("utf-8")) > budget_bytes:
        raise VaultError("budget_too_small", "Required context metadata cannot fit the requested budget.")
    for bundle in bundles:
        previous = len(packet["records"])
        packet["records"].extend(bundle)
        packet["omitted"]["budget"] -= len(bundle)
        if len(encode_packet(packet).encode("utf-8")) > budget_bytes:
            del packet["records"][previous:]
            packet["omitted"]["budget"] += len(bundle)
    if count and not packet["records"]:
        raise VaultError("budget_too_small", "No complete matching passage and required context can fit.")
    _fresh(vault, snapshot)
    return packet


def reindex(vault):
    """Publish an inspectable owner-local projection; memory remains authoritative."""
    snapshot, records, _ = _snapshot(vault)
    from .local_state import local_state_directory
    identity = hashlib.sha256((str(vault.root.resolve()) + "\0" + vault.vault_id).encode()).hexdigest()
    directory = local_state_directory(vault.root, "indexes")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (identity + ".sqlite3")
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".sqlite3")
    os.close(handle)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('snapshot',?)", (snapshot,))
        connection.execute("CREATE TABLE records(id TEXT PRIMARY KEY, revision TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.executemany("INSERT INTO records VALUES (?,?,?)",
                               [(r["id"], r["revision"], encode_packet(r)) for r in records])
        connection.commit()
        connection.close()
        connection = None
        _fresh(vault, snapshot)
        os.replace(temporary, destination)
    finally:
        if connection is not None:
            connection.close()
        Path(temporary).unlink(missing_ok=True)
    return {"records": len(records), "snapshot": snapshot, "path": str(destination)}
