"""Read-only, scope-first navigation over fresh, source-safe vault metadata."""

from __future__ import annotations

from collections import Counter

from .errors import VaultError
from . import retrieval


_LINK_LIMIT = 20
_METADATA = ("id", "revision", "title", "kind", "state", "scope")


def _metadata(record):
    return {field: record[field] for field in _METADATA}


def overview(vault, *, project=None, personal=False, audience="private", limit=100) -> dict:
    """List active and proposed records without inferring task or review status.

    Counts cover the entire admitted selection, before pagination. Exact source
    links and backlinks may point to safe records outside the returned page.
    Each edge list contains at most 20 entries, with explicit omission counts.
    Historical heads and sources used only by them are excluded. No record
    bodies, historical aliases, paths, or unavailable identifiers are returned.
    """
    retrieval._selection(project, personal, audience)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise VaultError("invalid_input", "Limit must be an integer between 1 and 100.")
    snapshot, all_records, grants = retrieval._snapshot(vault, project)
    permitted = [record for record in all_records
                 if retrieval._eligible(record, project, personal, audience, grants)]
    source_safe = retrieval._source_safe(permitted)
    _, historical_only = retrieval._candidates(source_safe, False)
    # Proposed records belong to this navigation view. A still-active source
    # they cite is current evidence for their review, even if an obsolete head
    # also cited it. It is not a source used only by history.
    proposed_sources = {source for record in source_safe.values()
                        if record["state"] == "proposed" for source in record.get("sources", [])}
    historical_only -= proposed_sources
    admitted = {identifier: record for identifier, record in source_safe.items()
                if record["state"] in {"active", "proposed"} and identifier not in historical_only}
    ordered = sorted(admitted)
    lineages = {}
    for identifier in ordered:
        record = admitted[identifier]
        lineage = record.get('lineage_id') or identifier
        lineages.setdefault(lineage, []).append(identifier)
    backlinks = {identifier: [] for identifier in ordered}
    for identifier in ordered:
        for source in admitted[identifier].get("sources", []):
            if source in admitted:
                backlinks[source].append(identifier)
    records = []
    for identifier in ordered[:limit]:
        record = admitted[identifier]
        sources = sorted(source for source in record.get("sources", []) if source in admitted)
        incoming = backlinks[identifier]
        rivals = lineages[record.get('lineage_id') or identifier]
        records.append({**_metadata(record), "evidence": record["evidence"],
                        "conflicts_with": [other for other in rivals if other != identifier],
                        "context_role": "reference_source" if record["kind"] == "source" else "memory",
                        "sources": [_metadata(admitted[source]) for source in sources[:_LINK_LIMIT]],
                        "backlinks": [_metadata(admitted[source]) for source in incoming[:_LINK_LIMIT]],
                        "omitted": {"sources": max(0, len(sources) - _LINK_LIMIT),
                                    "backlinks": max(0, len(incoming) - _LINK_LIMIT)}})
    result = {"schema_version": 1, "vault_id": vault.vault_id, "snapshot": snapshot,
              "provider": "off", "status": "ok" if ordered else "no_results",
              "selection": {"project": project, "personal": personal, "audience": audience,
                            "scope": "personal" if personal else f"project:{project}"},
              "total_count": len(ordered),
              "summary": {"by_kind": dict(sorted(Counter(record["kind"] for record in admitted.values()).items())),
                          "by_state": dict(sorted(Counter(record["state"] for record in admitted.values()).items())),
                          "conflicted_lineages": sum(len(values) > 1 for values in lineages.values())},
              "records": records,
              "omitted": {"limit": len(ordered) - len(records),
                          "source_dependencies": len(permitted) - len(source_safe)}}
    retrieval._fresh(vault, snapshot)
    return result
