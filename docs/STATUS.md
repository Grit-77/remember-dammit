# Source alpha status

Version 0.2.0a1, 2026-10-10. This describes implemented behavior; broader product
and harness proposals remain separate.

## Portable memory

New initialization uses format 2: immutable Markdown revisions, causal operations
and acknowledgement witnesses. Readers derive current state from the graph; no
format-2 sequence counter or authoritative mutable head file selects a winner.
Complete raw object union and explicit offline bundles preserve independent adds
and competing corrections from copies with the same vault ID.

The CLI exposes `heads`, `resolve` and `retract`. Resolution compares an exact
observed set of head IDs/revisions. An unseen branch remains visible when it
arrives later. Retraction is a lineage tombstone: history survives and an old
offline correction cannot restore the lineage. Grants remain specific to record
IDs; concurrent or old grants cannot cancel a known revoke. Scoped delivery
re-evaluates source eligibility after union.

`sync-export` publishes an immutable-object inventory with `COMPLETE.json`.
`sync-plan` previews a complete source bundle and proposed union; `sync-apply`
admits that reviewed inventory with exact-plan retry after partial publication.
`sync-import` combines fresh preview and application. Missing referenced or
advertised objects are incomplete transfers; changed committed bytes or an
invalid graph are integrity errors. Partial merge with missing witnessed
operations blocks content reads, including policy-dependent delivery.

An unknown branch omitted with its witnesses cannot be detected by a raw copy.
The format is not a consensus protocol or authenticated history. Bundles contain
all vault scopes for same-owner replication, unlike scoped Markdown exports.
No background transport is installed.

Existing v1 vaults remain readable/writable without automatic conversion.
`migrate-plan` and `migrate-apply` provide previewed, out-of-place conversion
with an untouched original and verified byte backup. Interrupted artifacts are
retained and marked; another attempt uses fresh paths. Rollback means selecting
the original or verified backup, which lacks later v2-only contributions.
See [MULTI-MACHINE.md](MULTI-MACHINE.md).

## Local tools and interfaces

The core retains source-linked records, corrections, history and explicit
personal/shared/project/session scopes. Retrieval validates sources, filters
scope/disclosure/dependencies, and uses lexical FTS passages, aliases and history.
Context packets have declared UTF-8 byte budgets, eligible conflict bundles and
omission notices. This is not universal semantic recall.

The owner CLI and optional SDK stdio MCP server share the core. MCP selection
is fixed at launch. Heads/resolution/retraction tools retain ownership and
source-scope checks; a project server cannot edit a granted personal record or
grant itself access. CLI subprocess and SDK protocol tests exercise interfaces;
native client behavior is separate acceptance.

Scoped overview provides metadata navigation and structured source/backlinks.
Markdown working copies preview title/body changes and apply guarded corrections.
Multi-head lineages require explicit resolution. Working folders are not
automatically refreshed. Import previews external Markdown and copies selected
source records without editing originals. Import/edit batches can be partial
and report their admitted progress.

Scoped Markdown export creates a new readable snapshot with completion markers.
Exported edits do not update canonical memory. Workspace setup previews/applies
client configuration and the packaged interview/readback skill while preserving
unrelated settings. `setup-check` inspects local readiness.

Configured Jev/Laya shadow assessment remains an explicit owner CLI path separate
from recall. Preview does not send a request or read credentials. Advice does not
write memory or change baseline result order. Protocol fixtures do not establish
live provider readiness or judgment quality.

## Local state and preservation

Locks, optional indexes and transfer staging use stable OS-user local state
outside portable content: Windows Local AppData, macOS Application Support,
or Linux `~/.local/state`. Environment-selected temp/cache paths do not create
separate lock authorities. Unsafe links and content-parent overlap are refused.
The advisory lock does not coordinate separate machines or OS users.

Canonical revisions are immutable; use working copies for supported Markdown
edits. Doctor reports conflicts, missing/changed committed content, orphan
payloads and pending files without deleting them. Tests exercise selected
process-death/publication boundaries, not every power-loss/filesystem mode;
Windows has no portable directory-fsync implementation here. Snapshots are
observations: revocation cannot retract text already delivered to a client.

## Remaining work and verification limits

Automatic editor refresh/text merge, background sync, automatic client
hooks/capture, embeddings, semantic extraction, passage-bound claim validation,
automatic downgrade/restore and history purging are outside this release. Owner
session records are explicit; MCP does not select arbitrary session scopes.

Local synthetic checks have been exercised on Windows. Those runs do not
establish cross-platform behavior. CI configuration targets Windows, macOS and
Linux with Python 3.11/3.12; consult actual results for the published commit.
Native Claude Code, Codex, Cursor and Antigravity acceptance and live sync-client
trials remain untested for this release. No live personal vault migration is claimed.

From an installed checkout:

```sh
python -m unittest discover -s tests -v
```

See [FACTS.md](../FACTS.md) for receipts and
[CI results](https://github.com/Grit-77/remember-dammit/actions/workflows/test.yml)
for actual jobs. This page intentionally gives no current test total.
