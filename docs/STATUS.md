# Source alpha status

Version 0.1.0a4, 2026-10-10. This document separates current implementation from the broader architecture proposals.

## Implemented

The local core initializes a new empty vault, persists immutable Markdown revisions, links records to sources, creates scoped corrections, preserves history, grants/revokes selected personal records, and diagnoses integrity and source-scope problems. A durable head checkpoint detects acknowledged journal-tail truncation, including lost revocations.

Retrieval validates canonical records, applies scope/disclosure/dependency rules, ranks heading/paragraph passages with SQLite FTS5, follows correction terminology, and returns bounded UTF-8 context. Historical-only sources are excluded from default recall so an obsolete instruction does not return through its old evidence. Explicit history remains available. This whole-source rule is conservative; it may exclude other useful passages from a source cited only by obsolete decisions. Passage-level evidence relationships remain future work.

The CLI and optional official-SDK MCP server invoke the same core. Project MCP servers have a fixed scope, cannot grant access, and cannot edit a granted personal record. Scope/source checks traverse dependencies and recheck the observed snapshot before returning. The context budget covers the canonical packet and its model-facing MCP text; protocol envelope overhead and client prompt overhead are outside that budget.

Four client proposal formats remain available read-only. Workspace setup can preview or merge the memory server entry and packaged skill, with local backups, conflict refusal and rollback attempts if a write fails. The skill guides a short interview, source-note capture, a chosen task and readback. Setup choices remain disabled; a separate owner CLI command can use explicitly configured Jev/Laya shadow assessment. Actual SDK subprocesses exercise the emitted argv for each format and project/personal mode. This is not native client acceptance.

The owner CLI can export a selected scope to a new Markdown snapshot folder, with a linked Home page and optional history. It refuses existing destinations, canonical-vault nesting and link/junction paths, filters inaccessible dependencies and marks interrupted exports incomplete. This is a readable snapshot, not editable-note synchronization; changes to exported files never write back into canonical memory.

Markdown import previews a bounded source folder, records content hashes and exclusions, and applies explicit source records to a separate initialized vault. Existing notes are never edited. Repeat plans reuse IDs; source changes produce revision-checked corrections. Batches are not atomic: inspect the returned complete/partial status and completed IDs before retrying.

The read-only setup-check command checks the selected configuration, packaged skill, isolated Python import and vault doctor. A ready report covers local files/runtime only; native trust and real client acceptance remain pending.

Optional advisor assessment is exposed through the owner CLI, not automatic MCP calls. It reports separate relevance advice from a hosted Jev endpoint or loopback Laya. Request previews do not send data or read credentials. Remote query approval, record/source egress checks, bounded transport and source freshness checks guard the explicit call. Tests use synthetic protocol responses; no live provider quality claim is made.

The scoped overview provides metadata-only navigation for active/proposed records, counts by kind/state, and exact structured source/backlinks. It is available through CLI and fixed-selection MCP. Counts cover the admitted selection; record/link limits report omissions. No task completion or semantic relationship is inferred.

Explicit Markdown authoring can open a new separate working folder, preview title/body edits and apply expected-revision corrections. It checks current source/scope policy against a snapshot inside the core writer lock. Workspaces remain unchanged after apply; historical receipts make identical retries idempotent. Batches can be partial, and inherited source references/grants are not automatically moved to successors. See [WORKING-NOTES.md](WORKING-NOTES.md).

## Storage boundaries

- Canonical revision files are under `.remember/revisions/`, with immutable operations and `head.json` as a durable high-water reference. They are human-readable, but not an ordinary freely editable Obsidian workspace yet.
- The alpha deliberately refuses initialization into a populated unrelated directory. It does not silently import or reorganize an existing vault.
- Editing a committed revision is reported as an integrity error. Use a separate working copy for supported title/body corrections; automatic materialized-note refresh and the full reconciliation workflow in VAULT.md remain unimplemented.
- Writer locks are in a stable `.remember-dammit-locks` directory beside the canonical vault root. This avoids different harness TEMP environments creating different locks and requires write access to the vault's parent. Locks are not portable memory and must not be synchronized.
- Tests cover process death around file flush/rename publication boundaries, not every possible power failure or filesystem failure mode. Windows lacks a portable directory-fsync operation here.
- Coordinated rollback of both the journal and its head checkpoint cannot be detected from those rolled-back files alone. This is integrity checking, not tamper-proof storage against someone controlling all local files.
- Snapshots are observed points in time. A revocation after the last delivery check cannot retract text already delivered to a client.
- No migration is provided for earlier private scratch formats from this development session. The initial distributed alpha format requires `head.json`.

## Not implemented

In-place vault adoption, automatic working-note refresh/text merge, automated semantic extraction, passage-bound claim validation, automatic ambiguity detection, multi-machine conflict merge/sync, migrations and restore tooling, background capture, automatic client hooks, embedding providers, result-changing advisor modes, automatic MCP advisor calls, and a visual vault manager.

Independent `session:<id>` records can be written by the owner CLI; project agents can save separate session-kind records in their bound project. MCP cannot select an arbitrary session scope. No automatic session card loading is claimed.

## Verification scope

Local execution is on Windows with Python 3.12.14, PyYAML 6.0.3 and MCP SDK 2.3.0. Tests use real temporary vaults, cross-process writers, interrupted commits, and actual stdio SDK clients. A missing Python 3.12-only pathlib method is simulated; it is not a native Python 3.11 run.

CI is configured for Windows, macOS and Linux on Python 3.11/3.12. Consult the [Actions results](https://github.com/Grit-77/remember-dammit/actions/workflows/test.yml) for the result on a specific commit; a configured matrix alone is not platform verification. No claim of a passing native Claude Code/Codex/Cursor/Antigravity matrix is made.

Run `python -m unittest discover -s tests -v` from the installed checkout to obtain the current result. Failure-injection cases intentionally exercise errors; recorded success must include the command's actual exit status.
