# Foundation implementation contract

Working internal API for 0.1.0a1. The public design remains broader; unsupported features must be labeled.

## Python boundaries

`storage.Vault(root: str | Path)` opens an initialized vault without creating it implicitly.

`Vault.initialize(root)` creates a new vault or returns an existing valid one, never overwriting invalid/existing user content. Returns `Vault`.

All operations return JSON-serializable dictionaries/lists. Domain failures raise `errors.VaultError(code, message)`.

Record dictionary fields: `id`, `revision` (digest), `kind`, `scope` (`personal`, `shared`, `project:<id>`, or `session:<id>`), `state` (`active`, `proposed`, `superseded`, `retracted`), `title`, `body`, `aliases` (list), `sources` (list of source IDs), `supersedes` (predecessor ID or null), `evidence` (`user-statement`, `source-excerpt`, `agent-inference`, `observation`), `disclosure` (`private`, `shared`, `public`), `remote_allowed` (bool), `actor`, `created_at`, and `path` (vault-relative readable note/revision path). Historical state is derived from committed corrections, not mutation of predecessor bytes. Source IDs must be existing eligible records in the same write scope or explicitly shared into the target project; no foreign-project source leakage.

Bodies must contain non-whitespace text. IDs are portable ASCII identifiers of at most 128 characters, with Windows reserved filenames and trailing dots excluded. Committed-head checkpoints protect against journal-tail loss; valid markers ahead of a checkpoint after interruption are recovered under the writer lock.

Storage methods (keyword arguments after the required ones):

- `put(*, title, body, scope, kind='note', aliases=None, sources=None, evidence='user-statement', disclosure='private', remote_allowed=False, record_id=None, operation_id=None, actor='local', state='active') -> record`
- `correct(record_id, *, expected_revision, title, body, operation_id=None, actor='local', aliases=None, sources=None) -> successor record` with a fresh ID and inherited scope/disclosure; include predecessor terms for lookup without returning old text as current.
- `get(record_id) -> record` including derived historical state; missing ID raises `not_found`.
- `list_records() -> list[record]` all committed records for owner inspection, validating integrity.
- `history(record_id) -> list[record]` full predecessor/successor lineage, oldest first.
- `grant(project, record_id, *, operation_id=None) -> dict` grants that personal record to a project; no automatic successor grant.
- `revoke(project, record_id, *, operation_id=None) -> dict`
- `grants_for(project) -> set[str]`
- `snapshot_id() -> str` fingerprint of committed operations and current policy.
- `doctor() -> dict` integrity and externally changed/invalid source diagnostics; do not silently repair.
- property `vault_id -> str`; property `root -> Path`.

Idempotency: repeating one operation ID with the same supplied request returns its original result, including after a correction; changed payload is `operation_conflict`. No shared mutable last-session file. Use unique scope-specific session records instead.

Managed writes publish immutable Markdown payloads plus one atomic commit marker per operation, under a cross-process writer lock with under-lock expected-base validation. Do not automatically overwrite existing human-editable files. The foundation may use committed readable revision files directly and report externally mutated payloads as integrity failures rather than claiming editor reconciliation is complete. Recovery ignores uncommitted orphan payloads and exposes committed corruption. Indexes never own content.

## Retrieval (manager-owned)

`retrieval.search(vault, query, *, project=None, personal=False, limit=10, include_history=False, audience='private') -> dict`

`retrieval.context(vault, query, *, project=None, personal=False, budget_bytes=8000, audience='private') -> dict`

`retrieval.encode_packet(packet) -> str` canonical compact JSON whose UTF-8 size is the budgeted output. `retrieval.reindex(vault) -> dict` rebuilds machine-local SQLite projection from committed records. A cache is optional/derived; scope/grants are always rechecked against live core state.

Require explicit project or personal selection; project sees that scope + `shared` + explicitly granted personal IDs, not all personal/session data. Audience filters visibility. Personal mode is explicitly owner-selected personal/shared only, not all projects. Sources and history follow identical eligibility rules. Default recall excludes proposed/superseded/retracted records. Results include sources, evidence, state, revision, score/reason and no-result/omission indicators. Provider mode is `off`; no network access is part of the core.

## Frontends (worker-owned)

CLI global `--vault PATH`, commands `init`, `remember`, `correct`, `recall`, `context`, `history`, `show`, `grant`, `revoke`, `doctor`, `reindex`, `mcp`, and `integration` if integration module is ready. Arguments map to the APIs above. Machine-readable JSON on stdout; errors JSON and nonzero exit. `context` prints `encode_packet` without extra bytes beyond the returned budget. No secrets or full vault listings in errors.

MCP optional extra: official Python SDK, local stdio only. Shared core calls, bounded input schemas. Server is launched with an explicit vault and immutable per-server project/personal selection; tools cannot widen that selection. Explicit memory read/write/correction/history tools, with source/scope validation. Do not expose `grant` or raw global `list_records` through agent tools. JSON-RPC/stdio must be exercised with an actual SDK client subprocess, not only function calls.

## Integration generator (separate worker-owned)

`integrations.render(harness, *, vault_path, project=None, personal=False, python_executable=None) -> dict` produces proposed MCP configuration and shared skill text without modifying installed client settings. Harness keys: `claude`, `codex`, `cursor`, `antigravity`. Return fields `harness`, `config_format`, `config_text`, `skill_text`, `instructions`, `tested_live=False`. Use explicit argv arrays and correct escaping. Test generated configuration by parsing it and starting its server command against a disposable vault when possible. CLI generator prints proposal only. No hooks/autoload claim.

## Ownership

- Storage worker: `storage.py`, `locking.py`, `tests/test_storage.py` and storage-specific test helpers.
- Frontend worker: `cli.py`, `mcp_server.py`, `__main__.py`, CLI/MCP tests.
- Integration worker: `integrations.py`, packaged templates, integration tests, `docs/INSTALL.md`.
- Manager: packaging, shared errors, retrieval, retrieval/end-to-end tests, documentation reconciliation, review and release decisions.

Everyone preserves others' changes. Standard test command: `python -m unittest discover -s tests -v`. Record focused red/green evidence and then run the complete suite when dependencies are available.
