# Browse and edit your vault

Memory should be easy to inspect and correct. This release adds a queryless overview and a deliberate Markdown editing roundtrip. It does not turn the canonical revision directory into an ordinary editable folder.

## See what is there

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" overview --project demo
```

Use `--personal` instead of `--project demo` for the personal selection. The CLI defaults to at most 100 records; `--limit` can request fewer. The MCP `overview` tool uses its already configured selection and defaults to 50 records. It cannot choose another project.

The overview contains titles, kinds, evidence labels, lifecycle states, exact source links and backlinks. It includes active and proposed records, with counts across the admitted selection and explicit omission counts. A `task` count means saved task records, not a count inferred to be unfinished. Proposed inferences remain labeled proposed.

Links come from structured source IDs; ordinary Markdown links are not interpreted as evidence. Each source/backlink list has at most 20 entries and reports further omitted links. Counts and links are filtered by scope, disclosure and source dependencies before delivery. No note bodies are included. Use `show` to inspect a selected record, or `context` when you need an explicit byte budget.

## Open a working copy

Choose a **new directory** outside the canonical vault, with an existing parent:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" edit-open --destination "C:/Working Notes/demo-round-1" --project demo
```

Open the resulting `Home.md` in a Markdown editor. It links to readable filenames, sources and backlinks. `notes/` contains editable active notes owned by the selected project or personal scope. `context/` contains admitted shared/granted context for reference; it is read-only in this editing flow.

Only change the `title` field and body of an editable note. Keep `rd_schema`, `rd_id` and `rd_base_revision` unchanged. Do not edit `manifest.json`, `Home.md`, completion markers or context files. The working copy preserves the base identity so a correction can be checked against the actual vault revision.

If `INCOMPLETE.md` is present, do not treat that folder as ready. An existing destination is refused, so opening cannot overwrite your files. Link/junction paths and overlap with canonical storage or writer locks are refused.

## Preview the actual changes

After editing, create a plan outside the working folder. This PowerShell 7 example assumes `C:/Private Plans` already exists:

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" edit-plan --workspace "C:/Working Notes/demo-round-1" --project demo | Set-Content -Encoding utf8NoBOM "C:/Private Plans/demo-round-1.json"
```

Read the plan's `status`, `changes`, `conflicts`, `skipped` and `warnings`. It contains actual before/after titles and bodies, expected revisions and file hashes. Keep this private: it includes selected note content. A ready plan is review data, not an access grant; apply independently checks the explicit selection and canonical records.

Missing notes do not delete memory. New files are skipped, not imported. Renaming a file appears as a missing note and an unsupported new file. Use the separate import workflow for new external Markdown, or the agent's `remember` tool for a new intentional memory. Modified read-only controls or identities are conflicts.

Correcting a cited source leaves existing citations on its predecessor. Review the dependency warning: related notes may be withheld from current recall until their evidence is deliberately reviewed and corrected. The system does not automatically rewrite their claims, citations or grants. A batch that edits both a source and an affected dependent is refused.

## Apply, then read back

```powershell
.venv/Scripts/python.exe -m remember_dammit --vault "C:/Memory Vault" edit-apply --workspace "C:/Working Notes/demo-round-1" --plan "C:/Private Plans/demo-round-1.json" --project demo
```

Apply checks every planned file and target before the first pending correction, then checks freshness for each write. A changed file, competing correction, access change or newly affected visible dependent requires a new preview. No automatic rebase replaces another agent's work.

Each successful correction creates a successor ID and retains its predecessor. The returned `successors` map identifies the new records. Use `show`, `history`, `recall` or `overview` to verify the actual vault result. Scope, evidence, source IDs and disclosure policy are inherited; this flow cannot grant access or enable remote assessment.

A batch is **not all-or-none**. The output distinguishes `complete`, `conflict` and `partial`, with admitted entries and a failed index when applicable. Conflict/partial CLI results exit nonzero. If interrupted, inspect the report and retry the same reviewed plan with the same working bytes; committed operation receipts prevent duplicate corrections. A replay acknowledges the original admission, even if that successor was subsequently corrected again. It does not assert that the old receipt is the current head.

## Start the next editing round

Apply leaves every working file unchanged, including the manifest. Open a new working folder to see the current heads before another editing round. This flow does not refresh the old folder, watch your editor, merge competing text or propagate file deletions. Explicit replica exchange is separate; see [MULTI-MACHINE.md](MULTI-MACHINE.md).

Working copies and plans contain permitted private information. Keep them outside public repositories. Current bounds are 1 MiB per input file, 16 MiB total workspace input and 4 MiB per plan; a large set of before/after changes may need smaller editing rounds. These are input limits, not a large-vault performance claim.

## Review offline conflicts

Format 2 retains both independently admitted corrections when offline replicas
exchange objects. A multi-head lineage needs an explicit resolution; the editing
preview does not select the last history entry or overwrite another branch.
Inspect the lineage with `history` and its current leaves with `heads`. History
order is for presentation, not a rule for choosing the current answer.

Save the `heads` JSON report outside the working folder and supply its path as
`--expected-heads` to `resolve`. The command compares every observed ID and
revision under the writer lock. A newly arrived head produces `stale_heads`;
review the enlarged set and preview again. A branch arriving after a valid
resolution remains another head if that resolution did not consume it. The
[replica guide](MULTI-MACHINE.md#resolve-competing-heads) contains the commands.

Resolution preserves the predecessors and their source records in history.
Omitted sources use the predecessor union only when eligible; select explicit
current sources when inherited evidence is no longer eligible. A new successor
ID inherits no personal sharing grant. `retract` uses the same exact head-set
guard to record a lineage tombstone, retaining history and bytes while omitting
that lineage from default recall. Deleting a working file does not retract it.
