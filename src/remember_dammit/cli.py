"""Owner CLI: explicit vaults, JSON results, and byte-exact context packets."""
import argparse
import json
import sys
from pathlib import Path
from .errors import VaultError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's message may repeat a sensitive argument supplied by a caller.
        raise VaultError("invalid_arguments", "Arguments missing or invalid; use --help for usage.")


def _selection(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project")
    group.add_argument("--personal", action="store_true")


def _write_fields(parser):
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--alias", action="append", dest="aliases")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--operation-id")
    parser.add_argument("--actor", default="local")


def _read_json(path, limit=4 * 1024 * 1024):
    try:
        with open(path, 'rb') as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError
        return json.loads(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise VaultError('invalid_plan', 'Specify a readable bounded UTF-8 JSON file.') from None


def _head_set(path):
    value = _read_json(path)
    values = value.get('heads') if isinstance(value, dict) else value
    if not isinstance(values, list) or len(values) > 1000:
        raise VaultError('invalid_heads', 'Expected heads must be an explicit list of IDs and revisions.')
    try:
        return [{'id': item['id'], 'revision': item['revision']} for item in values]
    except (KeyError, TypeError):
        raise VaultError('invalid_heads', 'Each expected head needs its ID and revision.') from None


def build_parser():
    parser = JsonArgumentParser(prog="remember-dammit", description="Local source-linked memory with explicit optional advisory assessment.")
    parser.add_argument("--vault", help="Explicit local vault directory (optional for import-plan and advisor-template)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize a vault without overwriting existing content")
    commands.add_parser('heads', help='Inspect every current head of a record lineage').add_argument('record_id')
    resolve = commands.add_parser('resolve', help='Resolve exactly the observed competing heads')
    resolve.add_argument('record_id')
    resolve.add_argument('--expected-heads', required=True, help='JSON heads report or ID/revision list')
    _write_fields(resolve)
    retract = commands.add_parser('retract', help='Create a portable lineage tombstone; retain history')
    retract.add_argument('record_id')
    retract.add_argument('--expected-heads', required=True)
    retract.add_argument('--operation-id')
    commands.add_parser('sync-export', help='Create a complete immutable transfer bundle').add_argument('--destination', required=True)
    commands.add_parser('sync-import', help='Validate and import a complete transfer bundle').add_argument('--bundle', required=True)
    commands.add_parser('sync-plan', help='Preview union with another copy of the same vault').add_argument('--source', required=True)
    commands.add_parser('sync-apply', help='Apply an unchanged reviewed union plan').add_argument('--plan', required=True)
    migration = commands.add_parser('migrate-plan', help='Preview explicit legacy-to-causal conversion')
    migration.add_argument('--destination', required=True)
    migration.add_argument('--backup', required=True)
    commands.add_parser('migrate-apply', help='Apply a migration preview with an untouched source and backup').add_argument('--plan', required=True)
    commands.add_parser('migrate-status', help='Inspect migration completion without opening the vault')
    remember = commands.add_parser("remember", help="Write a memory")
    _write_fields(remember)
    remember.add_argument("--scope", required=True)
    remember.add_argument("--kind", default="note")
    remember.add_argument("--evidence", choices=["user-statement", "source-excerpt", "agent-inference", "observation"], default="user-statement")
    remember.add_argument("--disclosure", choices=["private", "shared", "public"], default="private")
    remember.add_argument("--remote-allowed", action="store_true")
    remember.add_argument("--record-id")
    remember.add_argument("--state", choices=["active", "proposed"], default="active")
    correct = commands.add_parser("correct", help="Commit a correction with an expected revision")
    correct.add_argument("record_id")
    correct.add_argument("--expected-revision", required=True)
    _write_fields(correct)
    for name in ("recall", "context"):
        command = commands.add_parser(name)
        command.add_argument("query")
        _selection(command)
        command.add_argument("--audience", choices=["private", "shared", "public"], default="private")
        if name == "recall":
            command.add_argument("--limit", type=int, default=10)
            command.add_argument("--include-history", action="store_true")
        else:
            command.add_argument("--budget-bytes", type=int, default=8000)
    for name in ("show", "history"):
        commands.add_parser(name).add_argument("record_id")
    for name in ("grant", "revoke"):
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("record_id")
        command.add_argument("--operation-id")
    commands.add_parser("doctor")
    commands.add_parser("reindex")
    overview = commands.add_parser("overview", help="Browse scoped notes, tasks, proposals and exact source backlinks")
    _selection(overview)
    overview.add_argument("--audience", choices=["private", "shared", "public"], default="private")
    overview.add_argument("--limit", type=int, default=100)
    edit_open = commands.add_parser("edit-open", help="Create a new scoped Markdown working copy")
    _selection(edit_open)
    edit_open.add_argument("--destination", required=True)
    edit_plan = commands.add_parser("edit-plan", help="Preview title/body corrections from a working copy")
    _selection(edit_plan)
    edit_plan.add_argument("--workspace", required=True)
    edit_apply = commands.add_parser("edit-apply", help="Apply a reviewed editing plan with revision checks")
    _selection(edit_apply)
    edit_apply.add_argument("--workspace", required=True)
    edit_apply.add_argument("--plan", required=True, help="Reviewed JSON plan kept outside the working copy")
    export = commands.add_parser("export", help="Write a new read-only Markdown snapshot")
    _selection(export)
    export.add_argument("--destination", required=True)
    export.add_argument("--include-history", action="store_true")
    preview = commands.add_parser("import-plan", help="Preview a bounded read-only Markdown source import")
    preview.add_argument("--source", required=True, help="Absolute source directory; never modified")
    preview.add_argument("--collection", required=True)
    preview.add_argument("--scope", required=True)
    apply = commands.add_parser("import-apply", help="Apply an explicit import preview; retries use the same plan")
    apply.add_argument("--plan", required=True, help="Local JSON preview file")
    _selection(commands.add_parser("mcp", help="Serve local stdio MCP bound to one selection"))
    integration = commands.add_parser("integration", help="Print a client configuration proposal")
    integration.add_argument("harness", choices=["claude", "codex", "cursor", "antigravity"])
    _selection(integration)
    integration.add_argument("--python-executable", default=sys.executable)
    setup = commands.add_parser("setup", help="Preview or apply workspace MCP configuration and skill")
    setup.add_argument("harness", choices=["claude", "codex", "cursor", "antigravity"])
    _selection(setup)
    setup.add_argument("--workspace", required=True)
    setup.add_argument("--python-executable", default=sys.executable)
    setup.add_argument("--advisor", choices=["none", "jev", "laya"], default="none")
    setup.add_argument("--apply", action="store_true", help="Apply workspace configuration; otherwise preview only")
    check = commands.add_parser("setup-check", help="Inspect workspace installation without changing files")
    check.add_argument("harness", choices=["claude", "codex", "cursor", "antigravity"])
    _selection(check)
    check.add_argument("--workspace", required=True)
    check.add_argument("--python-executable", default=sys.executable)
    template = commands.add_parser("advisor-template", help="Print provider configuration; disabled unless shadow mode is selected")
    template.add_argument("provider", choices=["jev", "laya"])
    template.add_argument("--model", required=True)
    template.add_argument("--endpoint")
    template.add_argument("--api-key-env")
    template.add_argument("--mode", choices=["off", "shadow"], default="off")
    assess = commands.add_parser("assess", help="Assess scoped recall separately, without changing memory or result order")
    assess.add_argument("query")
    _selection(assess)
    assess.add_argument("--audience", choices=["private", "shared", "public"], default="private")
    assess.add_argument("--limit", type=int, default=5)
    assess.add_argument("--advisor-config")
    assess.add_argument("--allow-remote-query", action="store_true")
    assess.add_argument("--preview", action="store_true", help="Show eligible outbound requests without sending them or reading credentials")
    return parser


def _emit(value, *, packet=False):
    if packet:
        from .retrieval import encode_packet
        text = encode_packet(value)
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    # Bypass platform encoding and newline translation for the UTF-8 byte budget.
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(text)


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if args.command not in {"import-plan", "advisor-template"} and args.vault is None:
            raise VaultError("invalid_arguments", "An explicit --vault is required; use --help for usage.")
        if args.command == 'migrate-plan':
            from .migration import preview_migration
            result = preview_migration(args.vault, args.destination, args.backup)
        elif args.command == 'migrate-apply':
            from .migration import apply_migration
            plan = _read_json(args.plan)
            if not isinstance(plan, dict) or not isinstance(plan.get('source'), str) or Path(plan['source']).resolve() != Path(args.vault).resolve():
                raise VaultError('invalid_plan', 'Migration plan must match the explicitly selected source vault.')
            result = apply_migration(plan)
        elif args.command == 'migrate-status':
            from .migration import inspect_migration
            result = inspect_migration(args.vault)
        elif args.command == "advisor-template":
            from .advisors import validate_config
            config = {"schema": 1, "provider": args.provider, "mode": args.mode,
                      "model": args.model, "timeout_seconds": 5, "max_candidates": 3,
                      "endpoint": args.endpoint or ("https://api.typesafe.ai/v1/systemone" if args.provider == "jev" else "http://127.0.0.1:8765/v1/systemone")}
            if args.api_key_env is not None or args.provider == "jev":
                config["api_key_env"] = args.api_key_env or "TYPESAFE_API_KEY"
            result = validate_config(config)
        elif args.command == "assess":
            from .advisors import assess, load_config
            from .storage import Vault
            config = load_config(args.advisor_config, args.vault) if args.advisor_config else None
            result = assess(Vault(args.vault), args.query, project=args.project, personal=args.personal,
                            audience=args.audience, config=config, allow_remote_query=args.allow_remote_query,
                            preview=args.preview, limit=args.limit)
        elif args.command == "import-plan":
            from .importing import plan_import
            from .storage import Vault
            result = plan_import(args.source, collection=args.collection, scope=args.scope,
                                 vault=Vault(args.vault) if args.vault is not None else None)
        elif args.command == "setup-check":
            from .diagnostics import inspect_workspace
            result = inspect_workspace(args.workspace, args.harness, vault_path=args.vault,
                                       project=args.project, personal=args.personal,
                                       python_executable=args.python_executable)
        elif args.command == "setup":
            from .setup import setup_workspace
            result = setup_workspace(args.workspace, args.harness, vault_path=args.vault,
                                     project=args.project, personal=args.personal,
                                     python_executable=args.python_executable,
                                     advisor=args.advisor, dry_run=not args.apply)
        elif args.command == "integration":
            from .integrations import render
            result = render(args.harness, vault_path=args.vault, project=args.project, personal=args.personal, python_executable=args.python_executable)
        else:
            from .storage import Vault
            if args.command == "init":
                vault = Vault.initialize(args.vault)
                result = {"vault_id": vault.vault_id, "initialized": True}
            else:
                vault = Vault(args.vault)
                if args.command in {'heads', 'resolve', 'retract'}:
                    capability = {'heads': 'heads', 'resolve': 'resolve', 'retract': 'delete'}[args.command]
                    if not callable(getattr(vault, capability, None)):
                        raise VaultError('migration_required', 'This operation requires the causal format; preview migration first.')
                    if args.command == 'heads':
                        heads = vault.heads(args.record_id)
                        result = {'heads': heads, 'conflicted': len(heads) > 1, 'snapshot': vault.snapshot_id()}
                    elif args.command == 'resolve':
                        result = vault.resolve(args.record_id, expected_heads=_head_set(args.expected_heads),
                                               title=args.title, body=args.body, sources=args.sources,
                                               aliases=args.aliases, operation_id=args.operation_id, actor=args.actor)
                    else:
                        result = vault.delete(args.record_id, expected_heads=_head_set(args.expected_heads), operation_id=args.operation_id)
                elif args.command in {'sync-export', 'sync-import', 'sync-plan', 'sync-apply'}:
                    from .replication import export_bundle, import_bundle, plan_merge, apply_merge
                    if args.command == 'sync-export':
                        result = export_bundle(vault, args.destination)
                    elif args.command == 'sync-import':
                        result = import_bundle(vault, args.bundle)
                    elif args.command == 'sync-plan':
                        result = plan_merge(vault, args.source)
                    else:
                        result = apply_merge(vault, _read_json(args.plan, 16 * 1024 * 1024))
                elif args.command == "edit-open":
                    from .editing import open_editing
                    result = open_editing(vault, args.destination, project=args.project, personal=args.personal)
                elif args.command == "edit-plan":
                    from .editing import plan_edits
                    result = plan_edits(vault, args.workspace, project=args.project, personal=args.personal)
                elif args.command == "edit-apply":
                    from .editing import apply_edits, MAX_PLAN_BYTES
                    try:
                        with open(args.plan, "rb") as handle:
                            payload = handle.read(MAX_PLAN_BYTES + 1)
                        if len(payload) > MAX_PLAN_BYTES:
                            raise ValueError
                        plan = json.loads(payload.decode("utf-8"))
                    except (OSError, ValueError, UnicodeError, RecursionError):
                        raise VaultError("invalid_plan", "Specify a readable, bounded editing JSON preview.") from None
                    result = apply_edits(vault, args.workspace, plan, project=args.project, personal=args.personal)
                elif args.command == "overview":
                    from .overview import overview
                    result = overview(vault, project=args.project, personal=args.personal,
                                      audience=args.audience, limit=args.limit)
                elif args.command == "remember":
                    result = vault.put(**{key: value for key, value in vars(args).items() if key not in {"command", "vault"}})
                elif args.command == "correct":
                    result = vault.correct(args.record_id, **{key: value for key, value in vars(args).items() if key not in {"command", "vault", "record_id"}})
                elif args.command in {"grant", "revoke"}:
                    result = getattr(vault, args.command)(args.project, args.record_id, operation_id=args.operation_id)
                elif args.command in {"show", "history", "doctor"}:
                    operation = getattr(vault, "get" if args.command == "show" else args.command)
                    result = operation(args.record_id) if args.command != "doctor" else operation()
                elif args.command == "mcp":
                    from .mcp_server import create_server
                    create_server(vault, project=args.project, personal=args.personal).run(transport="stdio")
                    return 0
                elif args.command == "export":
                    from .exporting import export_snapshot
                    result = export_snapshot(vault, args.destination, project=args.project,
                                             personal=args.personal, include_history=args.include_history)
                elif args.command == "import-apply":
                    from .importing import apply_import, MAX_PLAN_BYTES
                    try:
                        with open(args.plan, "rb") as handle:
                            payload = handle.read(MAX_PLAN_BYTES + 1)
                        if len(payload) > MAX_PLAN_BYTES:
                            raise ValueError
                        plan = json.loads(payload.decode("utf-8"))
                    except (OSError, ValueError, UnicodeError, RecursionError):
                        raise VaultError("invalid_plan", "Specify a readable, bounded import JSON preview.") from None
                    result = apply_import(vault, plan)
                else:
                    from . import retrieval
                    if args.command == "reindex":
                        result = retrieval.reindex(vault)
                    else:
                        fields = {key: value for key, value in vars(args).items() if key not in {"command", "vault", "query"}}
                        operation = retrieval.search if args.command == "recall" else retrieval.context
                        result = operation(vault, args.query, **fields)
        _emit(result, packet=args.command == "context")
        if args.command == "import-apply" and result["status"] == "partial":
            return 1
        if args.command in {"edit-plan", "edit-apply"} and result.get("status") in {"conflict", "partial"}:
            return 1
        if args.command == 'doctor' and result.get('ok') is False:
            return 1
        if args.command == 'migrate-status' and result.get('state') != 'complete':
            return 1
        if args.command.startswith(('sync-', 'migrate-')) and isinstance(result, dict) and (result.get('complete') is False or result.get('status') in {'conflict', 'partial', 'incomplete', 'invalid'}):
            return 1
        return 0
    except VaultError as exc:
        error = {"code": exc.code, "message": exc.message}
        if getattr(exc, "evidence", None) is not None:
            error["evidence"] = exc.evidence
        _emit({"error": error})
        return 2 if exc.code == "invalid_arguments" else 1
    except ImportError:
        _emit({"error": {"code": "dependency_missing", "message": "Required component unavailable; MCP requires the mcp extra."}})
        return 1
    except (OSError, ValueError):
        _emit({"error": {"code": "operation_failed", "message": "Local operation failed; check arguments and vault access."}})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
