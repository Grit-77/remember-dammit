# Vault format and authority

Implemented format 2 in source alpha 0.2.0a1. Broader organization and automation
ideas in [PRODUCT.md](PRODUCT.md) are separate from this storage contract.

## Portable objects

```text
My Vault/
  .remember/
    vault.json                  immutable schema, vault ID, initial grants
    revisions/<sha256>.md       immutable exact Markdown bytes
    operations/<digest>.json    immutable causal operations
    acks/<operation>.json       immutable acknowledgement witnesses
```

Each operation contains its vault ID, request operation ID and request digest,
observed parent frontier, action, admitted result and consumed predecessor IDs.
Its digest names the canonical JSON object. A revision's SHA256 names its exact
bytes. Timestamps are display metadata; they do not select correction or policy
winners. Format 2 has no authoritative mutable `head.json` or sequence counter.

Readers validate immutable objects and derive the causal graph directly. The
snapshot depends on immutable configuration and operation digests, rather than
arrival order, a local path, indexes or acknowledgement order. A complete object
union of valid format-2 copies with the same vault identity can be opened without
an extra merge operation. Separately initialized vaults have distinct identities.
See [MULTI-MACHINE.md](MULTI-MACHINE.md) for exchange commands.

Bundles include the managed immutable objects and a final inventory marker,
not local locks, indexes, provider settings or machine bindings. A bundle is a
full same-owner replica transfer, including personal content. Scoped Markdown
snapshots are a different output for selected readable content.

## Heads, history and retries

Records retain body text, kind, scope, state, evidence class, disclosure policy,
source IDs and aliases. A correction creates a new record ID and revision rather
than overwriting its predecessor. Source links identify specific records; they
do not automatically follow a correction to a new ID.

Format 2 projects `lineage_id`, `supersedes_all` and `conflicts_with` alongside
existing fields. `heads(record_id)` returns a lineage's current leaves.
`history(record_id)` returns retained records in deterministic parent-before-child
order. The last history entry is not a current-head selector. Offline competing
corrections remain separate heads with their bodies and evidence preserved.
Scoped recall/context report eligible conflicts rather than choosing a winner.

`correct` requires the locally sole current head and expected revision. `resolve`
requires the exact nonempty set of observed head IDs/revisions. Another arriving
branch invalidates an old set with `stale_heads`. A branch arriving after a valid
resolution remains a competing leaf if that resolution did not consume it.
Ordinary scope, metadata and source-eligibility checks also apply to resolution.

Request operation IDs support exact retries of their historical admitted result,
including after later corrections. Reusing an ID with a different request or
different result creates `operation_conflict`: sound operations are retained,
diagnostics name the ambiguity, and retry of that ID is refused. Different
content claiming one record identity is `identity_conflict`; no filename or
timestamp rule resolves it by overwriting a revision.

## Scope and remove-wins policy

Personal, shared, project and explicit owner session scopes remain distinct.
Project delivery can include its records, shared records and specifically granted
personal IDs, subject to disclosure and dependency checks. A fixed-selection MCP
server cannot choose another project or grant itself access. These checks govern
core outputs; they do not sandbox a client with direct filesystem access.

Initial grants live in immutable configuration. Later grants/revokes are causal
operations. For an exact project/record key, a grant is effective only when it
has observed every known revoke; an old or concurrent grant cannot cancel a
revoke. An intentional later grant can reauthorize that exact ID after seeing
the revocations. A correction or resolution's new ID inherits no grant. Merged
recall/context delivery re-evaluates eligibility and withholds content whose source dependencies
are no longer disclosed or active.

`retract` records a lineage tombstone with the exact-head guard. It retracts the
lineage and descendants, including corrections admitted on an older offline
copy. Replaying old bytes or granting a record does not restore that lineage.
Default recall/context omit it; explicit history retains the records and doctor
reports tombstone evidence. Content erasure and automatic restoration are not
provided by this command.

## Publication and incomplete copies

Managed writes publish immutable payloads and operations, then acknowledgement
witnesses. The operation marker is the admission point. A valid marker without
its acknowledgement can survive a crash; exact retry repairs the missing
witness. An unreferenced payload is not admitted as a record.

Explicit merge validates the complete proposed union before admission. It
publishes witnesses for validated operations before new operation markers,
including a witness for a crash-surviving operation with no source acknowledgement.
A partial copy with missing witnessed operations refuses ordinary reads/writes,
rather than exposing a grant before the advertised revoke arrives. Exact-plan
retry permits progress confined to its reviewed inventory; unrelated source or
target changes require a fresh preview.

| Condition | Meaning |
| --- | --- |
| Missing referenced parent, payload or acknowledged operation | `incomplete_transfer`; retain bytes and supply missing objects from another copy. |
| Changed digest-named payload, malformed committed operation or invalid causal graph | `integrity_error`; preserve objects and inspect a sound copy. |
| Different vault identity on transfer | `vault_mismatch`; separate vaults are not replicas. |
| Ambiguous request or record identity | `operation_conflict` or `identity_conflict`; retain contributions and inspect diagnostics. |
| Unreferenced payload or pending publication file | Doctor reports orphan/uncommitted files; they are not automatically admitted or deleted. |

A bundle inventory detects omitted advertised objects. A raw copy cannot reveal
an entirely unknown branch omitted with its witnesses. Restoring a complete older
tree with no retained later witness is indistinguishable from genuinely older
history. The format does not establish consensus or authenticated authorship.

## Machine-local state

Writer locks, optional SQLite projections and transfer staging use a stable
per-user OS-local namespace outside the vault. Windows uses the account's Local
AppData known folder; macOS uses `~/Library/Application Support`; Linux uses the
account home's `~/.local/state`. A normalized resolved root identifies the local
namespace before initialization and after reopening.

Temp/cache environment variables do not choose another writer-lock authority.
Linked state paths and overlap with the vault or its selected content parent
are rejected; account-home and filesystem-root container parents are handled
separately. There is no sibling `.remember-dammit-locks` directory. `reindex`
rebuilds a disposable local SQLite projection; search validates source data and
builds its scoped FTS index in memory.

Locks serialize participating threads/processes for one OS user on one machine,
and are released on process death. They are advisory, not distributed locks.
External file arrival is handled through validation and snapshot rechecks.
Different OS users do not coordinate through this namespace; bind-mount/hardlink
aliases are not established as the same root.

## Legacy format and migration

Format-1 vaults remain readable/writable through the preserved implementation.
That single-chain format uses legacy `head.json` and cannot represent independent
sequence branches. Opening it does not convert it.

`migrate-plan` binds a validated source snapshot and complete byte inventory to
new destination/backup paths. `migrate-apply` verifies a byte-for-byte backup,
converts into a separate v2 directory, and checks source, destination and final
backup before reporting success. Vault/record identities, committed revision
bytes, request identities and policy semantics are preserved. Original files
remain usable. Interrupted destinations retain an incomplete marker. Recovery
uses a new preview with fresh paths.

Rollback is explicit path selection: keep using the original or select the
verified backup. V2-only contributions are absent there; preserve/export those
before discarding a new copy. No automatic in-place migration, cleanup or
downgrade of a multi-head graph is provided. See [MULTI-MACHINE.md](MULTI-MACHINE.md).
