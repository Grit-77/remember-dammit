# Offline replicas, transfer and migration

Source alpha 0.2.0a1 retains independent contributions from offline copies of
one owner's vault. Explicit object exchange is implemented through the CLI.
No background sync service is installed by this package. A separate private
Syncthing trial and native Codex CLI observations are described in the
[bounded acceptance report](LIVE-ACCEPTANCE.md); other native acceptance remains open.

## Start with one vault identity

Initialize once, from an installed checkout:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/desktop" init
```

For another machine, copy that vault's `.remember/vault.json`, `revisions/`,
`operations/` and `acks/` into the same managed layout at a separate vault root.
Preserve exact bytes. Independent initialization creates a different vault ID
and is not a replica of the first vault. Machine paths may differ.

The examples use PowerShell 7. On macOS/Linux substitute `.venv/bin/python`
and appropriate absolute paths, retaining the CLI arguments. Save plans as UTF-8
without a BOM and create the private plan folder first. These example paths do
not change your client configuration automatically.

Locks, optional indexes, transfer staging, client configuration and credentials
stay machine-local. The core uses OS-account local state under Windows Local
AppData, macOS `~/Library/Application Support` or Linux `~/.local/state`.
Temp/cache environment variables do not select another lock authority. Rebuild
the disposable projection after a content-only copy:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" doctor
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" reindex
```

The per-user lock coordinates cooperating writers on one machine, not separate
machines. Immutable objects and snapshot rechecks handle replica arrival; no
clock or machine preference chooses a conflicting winner.

## Export and review a bundle

Choose a new output directory on the source:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/desktop" sync-export --destination "C:/PrivateTransfers/from-desktop-1"
```

Move the completed bundle by your chosen transport. `COMPLETE.json` binds its
sorted paths, sizes, hashes, vault ID, snapshot and operation frontier. Default
limits are 100,000 objects and 1 GiB of object bytes; the receiving API also checks
the proposed union against its configured bounds. A missing completion marker
means this is not a completed bundle.

This full-vault transfer includes personal records for the same owner. The scoped
`export --project ...` Markdown snapshot command is a different readable output,
not a replica bundle.

Preview at the target, using the bundle's actual local path:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" sync-plan --source "C:/PrivateTransfers/from-desktop-1" | Set-Content -Encoding utf8NoBOM "C:/PrivatePlans/merge-1.json"
```

Inspect added/identical objects, lineage and operation conflicts, effective policy
changes and snapshots. The plan contains local paths and policy details; keep it
as an owner-local review artifact. Apply that exact reviewed plan:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" sync-apply --plan "C:/PrivatePlans/merge-1.json"
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" doctor
```

Application validates the complete proposed union before admitting objects. It
compares existing immutable bytes rather than overwriting them. The same plan
can resume partial progress confined to its inventory; unrelated changes require
a fresh preview. Repeated completed application adds no duplicate records.
For a deliberate fresh preview-and-apply in one command:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" sync-import --bundle "C:/PrivateTransfers/from-desktop-1"
```

Exchange the other copy's contributions back as a new bundle. Complete object
union converges after the contributions arrive; one one-way transfer does not
prove that every copy contains every branch.

## Resolve competing heads

After offline competing corrections, replace `record-id` with a real lineage
member, inspect history and save the current heads report:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" history record-id
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" heads record-id | Set-Content -Encoding utf8NoBOM "C:/PrivatePlans/heads.json"
```

Read the bodies and sources, then consume the exact observed set:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" resolve record-id --expected-heads "C:/PrivatePlans/heads.json" --title "Reviewed decision" --body "Decision after reviewing the competing contributions." --operation-id resolution-1
```

`--expected-heads` takes a saved heads report or JSON list of `id`/`revision`
objects. Missing, extra or changed heads produce `stale_heads`; inspect the
current set before making a new intent. A later branch not consumed by resolution
remains a head. History retains predecessors; its last item does not choose
the current answer. Optional repeated `--source` selects eligible evidence.
Omitted sources use the predecessor union only if still eligible. New successor
IDs inherit no personal sharing grant. Exact operation retries return historical
receipts; use a new operation ID for a new intent.

Retraction uses a fresh exact head set:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" heads record-id | Set-Content -Encoding utf8NoBOM "C:/PrivatePlans/retract-heads.json"
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/laptop" retract record-id --expected-heads "C:/PrivatePlans/retract-heads.json" --operation-id retraction-1
```

This tombstone retains history/bytes and retracts old offline descendants after
exchange. `heads` can still show retained leaves with `state: retracted`.
Purging bytes and restoring a tombstoned lineage are not part of this command.

A concurrent revoke defeats a grant that has not observed it. An intentional
later grant after observing the revocations can reauthorize only the exact ID.
Merged delivery withholds personal sources and dependent content when their
effective grant is absent.

## Interrupted, incomplete and corrupt copies

Inspect JSON results. A partial merge reports `complete: false`,
`transfer_interrupted` and retry information; CLI exit is nonzero. Preserve
admitted objects and retry the unchanged plan, or preview again after unrelated
source/target changes.

The importer publishes validated operation witnesses before new markers. Missing
witnessed operations cause `incomplete_transfer` for ordinary reads/writes, so
an old grant prefix cannot become visible while its advertised revoke is absent.
Process death releases the local lock. A standalone valid operation without an
acknowledgement is a crash survivor; exact write retry repairs its witness.

Missing referenced parents/payloads, missing acknowledged operations, and missing
advertised bundle objects are incomplete transfers. Changed committed bytes or
invalid causal structure are integrity errors. Unsupported/traversing/linked
bundle paths are rejected; different vault identities cannot be merged. Doctor
reports orphan payloads and pending files without automatically deleting them.

A raw copy cannot reveal an entirely unknown branch omitted with its witnesses.
A manifest detects advertised omissions, not history the sender never advertised.
Removing an operation and its witnesses, or restoring an entire older tree
without retained later evidence, can look like a valid older vault. This is not
authenticated authorship, consensus or rollback-proof storage. Native transport
behavior needs its own trials.

## Preview format-1 migration

Installing this release or opening v1 does not convert it. A valid v1 vault stays
readable/writable, but its single chain cannot represent independent offline
branches. Select separate new destination and backup paths:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/legacy" migrate-plan --destination "C:/MemoryCopies/converted-v2" --backup "C:/MemoryBackups/legacy-before-v2" | Set-Content -Encoding utf8NoBOM "C:/PrivatePlans/migration.json"
```

Preview validates the source and binds its complete byte inventory and snapshot;
it writes neither destination nor backup. Inspect paths, counts and plan binding.
The backup covers owner files as well as managed source content. Apply with the
original source explicitly selected:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/legacy" migrate-apply --plan "C:/PrivatePlans/migration.json"
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/converted-v2" migrate-status
.venv/Scripts/python.exe -m remember_dammit --vault "C:/MemoryCopies/converted-v2" doctor
```

Application rechecks source bytes, validates a byte-for-byte backup, converts
into a separate tree, and verifies record/policy semantics and final backup
before success. Vault/record IDs, committed revision bytes and request identities
are preserved. Clients are not automatically switched to the new path.

Stale source, occupied destination or incomplete backup prevents successful
conversion. Interrupted artifacts remain; `migrate-status` reports the marker
without opening an incomplete tree as a vault. Continue with the original and
preview another attempt using fresh paths. Failed attempts are not overwritten
or automatically deleted.

Before switching clients, rollback means continuing to use the untouched source.
After switching, explicitly choose the original or verified backup again. That
copy lacks v2-only contributions: preserve/export the v2 copy before destructive
cleanup. No automatic downgrade of a multi-head graph is provided. An invalid
v1 fork with colliding sequence operations is not a valid migration source;
preserve its copies rather than choosing a checkpoint winner.
