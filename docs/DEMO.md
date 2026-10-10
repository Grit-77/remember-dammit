# Demo and validation plan

Design only. No live four-harness recording or compatibility test has been completed.

The provider-free [core demo script](../examples/demo.py) now exercises actual persistence, correction, reopened recall and project isolation. It is separately tested and does not invoke or impersonate any native harness.

## The story

**One vault grows more useful as you switch tools.**

Use the [illustrative vault](../examples/vault/Home.md) as the broader synthetic storyboard. The core script above implements a smaller real fixture; the four-client sequence below is still a planned acceptance run.

1. In Claude Code, save a scoped preference and a source-backed project decision.
2. In Cursor, retrieve project context and use the shared preference without receiving unrelated private material.
3. In Antigravity, correct the project decision and save an outcome in its own session card.
4. In a fresh Codex session, retrieve the corrected decision and relevant continuation card, with links to the source and predecessor.
5. Open the same vault in Obsidian or a text editor: show the knowledge link, source, correction history, and separate session cards.

A 60–90 second edited overview can show the experience. Publish the full reproduction separately; cuts are not latency measurements.

## What the demonstration must prove

- All four clients use the same vault ID and memory IDs; no copied client-specific knowledge stores.
- Correction history remains inspectable; the old decision is not delivered as current.
- Context shows why each source was selected and distinguishes saved assertions from independent evidence.
- Another project cannot accidentally recall the fixture's scoped decisions.
- Each writer owns a distinct session card. Parallel work does not overwrite a global last-session summary.
- The complete mandatory flow works with optional providers disabled.

## Real-client acceptance record

For each target, record the client/surface version, platform, adapter version, transport, starting state, explicit invocation or native event, context delivered, IDs/revisions, answer, writes, and limitations.

Run explicit recall/save first. Run automatic start/resume/compaction separately where supported. Model and integration behavior are separate observations: correct retrieved context does not prove the model followed it.

## Additional fixtures

- Two sessions propose competing corrections to the same base revision.
- A human edits a source while an agent prepares a change.
- A search index is deleted and rebuilt.
- A note is moved, duplicated, made private, or tombstoned.
- A provider times out, returns unknown IDs, or assesses a source changed mid-call.
- English/Turkish source and query pairs, including cases lexical search should honestly miss.
- Two machines make offline changes; no last-writer-wins resolution is silently applied.

Native cross-machine sync and provider tests are later release gates, not prerequisites for demonstrating a provider-free local vault.

## Claims discipline

Use synthetic data and publish actual reproduction commands with the implementation. Do not label mock output as a working demo, automatic extraction as guaranteed truth, a documented hook as tested integration, or a self-reported outcome as independent evidence.
