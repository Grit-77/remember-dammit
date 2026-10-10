"""Owner CLI: explicit vaults, JSON results, and byte-exact context packets."""
import argparse
import json
import sys
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


def build_parser():
    parser = JsonArgumentParser(prog="remember-dammit", description="Local source-linked memory. No provider calls.")
    parser.add_argument("--vault", help="Explicit local vault directory (optional for import-plan)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize a vault without overwriting existing content")
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
        if args.command != "import-plan" and args.vault is None:
            raise VaultError("invalid_arguments", "An explicit --vault is required; use --help for usage.")
        if args.command == "import-plan":
            from .importing import plan_import
            from .storage import Vault
            result = plan_import(args.source, collection=args.collection, scope=args.scope,
                                 vault=Vault(args.vault) if args.vault is not None else None)
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
                if args.command == "remember":
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
