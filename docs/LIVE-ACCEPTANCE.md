# Native clients and live transport: bounded acceptance report

Implementation: `44e45e2bf11cdbae23c0d1e82f689393f80d1769` (0.2.0a1).
Run date: 2026-10-10. This project-maintained report describes a private,
synthetic test on actual Windows, macOS and Linux machines. It is separate
from the public CI matrix. Raw native transcripts, machine bindings and
transport configuration stay private; the sanitized evidence index identifies
the observed checks and receipt hashes: [evidence index](evidence/live-acceptance-2026-10-10.json).

## Native model sessions

| Client / platform | Observed version | Result |
| --- | --- | --- |
| Codex CLI / Windows | 0.160.1 | Passed scoped MCP write, read and fresh-session recall. |
| Codex CLI / macOS | 0.162.0 | Passed fresh-session cross-host recall and write. |
| Codex CLI / Linux | 0.160.1 | Passed fresh-session cross-host recall and write. |
| Claude Code / Windows | 2.1.289 | Blocked by an authenticated subscription quota before tool calls. |
| Claude Code / macOS | 2.1.287 | Remote CLI session could not authenticate; no tool calls. |
| Claude Code / Linux | 2.1.291 | Blocked by an authenticated subscription quota before tool calls. |

The native Codex chain wrote on Windows, recalled and wrote on macOS, recalled
and wrote on Linux, then recalled the Linux contribution in a fresh Windows
session. Receiving prompts supplied the lookup title, not the stored nonce or
record ID. Actual MCP call/results were compared with independent vault reads.
No manual vault copy or bundle import transported these contributions.

A further Windows session corrected its own record, read history, recalled
using former terminology, repeated the exact correction without a duplicate,
and received scope-denied results. After offline branches merged, another
read-only native session saw all three conflicting heads and the context
warning. Direct reads of a revoked personal source, its history and its
dependent note were denied. The read-only session left the snapshot unchanged.

These runs used existing subscription authentication and native approval
review. The requested Codex profile was `gpt-6.1-sol` with high reasoning;
its native JSON did not independently report effective model/effort. The
Claude runs did not establish functional acceptance. Desktop GUI behavior,
Cursor, Antigravity and automatic lifecycle recall were not tested here.

## Live synchronization

Separate Syncthing 2.1.6 processes used a single synthetic vault identity,
explicit TCP peers and isolated state/configuration. Existing live services
and memory were outside the test. The Mac and Linux copies began empty and
received the seed through the test transport.

With the test folders paused, each host added a different project contribution
and corrected the same original decision. Windows and Mac first converged on
two heads while Linux remained isolated; Linux's return produced three heads.
The compared immutable file inventories equaled the union of the offline
copies, including exact file hashes. Sources and correction history survived.

A resolution using the older two-head set failed with `stale_heads` and left
the snapshot unchanged. A fresh resolution consumed all three heads; repeating
it and rescanning the transport did not duplicate the operation. A tombstone
retracted an old offline descendant, and a revoke defeated the stale grant.
Scoped recall/context withheld the revoked source and its dependent content.

For partial arrival, one new operation was withheld outside the source's sync
folder while its revision and acknowledgement traveled normally. Both remote
readers reported `incomplete_transfer`. Restoring that operation only at the
origin allowed automatic recovery, preserving previously stored bytes.

The dedicated Linux sync process was also shut down gracefully. A new local
CLI write/read succeeded while Windows and Mac still reported that record
absent. Restarting the same isolated sync process delivered it automatically
to the other hosts with matching records and snapshots. This was a controlled
process restart, not a machine power loss or forced crash.

On each host, the test vault's disposable index was removed and rebuilt. The
canonical snapshot, semantic view and immutable file inventory stayed equal.
Indexes, locks, client settings and transport credentials remained outside the
synchronized vault.

The retained dependent record deliberately produces a `source_scope` doctor
diagnostic after its source grant is revoked. This expected review item is
not reported as a clean doctor result or silently repaired by deleting history.

The three dedicated sync processes were shut down after verification. Process
and listener observations confirmed they stopped while the existing live
Syncthing processes remained present. Synthetic fixtures and private receipts
were retained for review; no service or autostart entry was installed.

## Limits

This is a bounded observed trial, not a transport certification or a durability
benchmark. A raw sync client cannot reveal an entirely unknown branch omitted
with all of its witnesses. Raw folder synchronization is not atomic; a valid
older prefix can remain visible before a previously unknown branch arrives.
The application refuses known missing dependencies once their witnesses arrive.

No live personal vault was migrated. Retraction retains physical history;
physical erasure, automatic downgrade, exhaustive filesystem/power-loss tests
and universal native-client compatibility remain outside this report.
