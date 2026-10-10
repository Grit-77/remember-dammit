"""Optional official MCP v2 server with a fixed local vault and selection."""
import json
from typing import Annotated, Any, Literal
from pydantic import Field
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from .errors import VaultError
from . import retrieval


ShortText = Annotated[str, Field(min_length=1, max_length=256)]
BodyText = Annotated[str, Field(min_length=1, max_length=100_000)]
QueryText = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
AliasList = Annotated[list[ShortText], Field(max_length=100)]
SourceList = Annotated[list[Identifier], Field(max_length=100)]


def create_server(vault, *, project=None, personal=False):
    """Bind one immutable read selection and its narrower write scope."""
    if bool(project) == bool(personal):
        raise VaultError("invalid_selection", "Select exactly one project or personal memory.")
    write_scope = "personal" if personal else f"project:{project}"
    selection = {"project": project, "personal": personal, "audience": "private"}
    # Reuse the core's selection validation before exposing a transport.
    retrieval.visible_record(vault, {"scope": write_scope, "disclosure": "private"}, **selection)
    server = MCPServer("remember-dammit", instructions="Local source-linked memory. Recall before answering; write only intentional memory. This server is bound to one selection and never calls providers.")

    def visible(record):
        pending = [record]
        seen = set()
        while pending:
            current = pending.pop()
            if current["id"] in seen:
                continue
            seen.add(current["id"])
            if not retrieval.visible_record(vault, current, **selection):
                return False
            for source_id in current.get("sources", []):
                try:
                    pending.append(vault.get(source_id))
                except VaultError as exc:
                    if exc.code == "not_found":
                        return False
                    raise
        return True

    def read_record(record_id):
        try:
            record = vault.get(record_id)
        except VaultError as exc:
            if exc.code == "not_found":
                raise VaultError("not_found", "Record is unavailable in this server selection.") from None
            raise
        if not visible(record):
            raise VaultError("not_found", "Record is unavailable in this server selection.")
        return record

    def clean_record(record):
        result = dict(record)
        result["sources"] = []
        for source_id in record.get("sources", []):
            try:
                read_record(source_id)
            except VaultError as exc:
                if exc.code == "not_found":
                    continue
                raise
            result["sources"].append(source_id)
        predecessor = record.get("supersedes")
        if predecessor:
            try:
                read_record(predecessor)
            except VaultError as exc:
                if exc.code != "not_found":
                    raise
                result["supersedes"] = None
        return result

    def validate_sources(sources):
        for source_id in sources or []:
            read_record(source_id)

    def invoke(operation, *, writes=False):
        try:
            snapshot = None if writes else vault.snapshot_id()
            result = operation()
            if not writes and vault.snapshot_id() != snapshot:
                raise VaultError("concurrent_change", "Vault changed during the read; retry.")
            return result
        except VaultError as exc:
            # Integrity errors can arise in global committed data: never repeat
            # their record paths or details into a scoped agent transport.
            message = "Local memory operation failed." if exc.code != "not_found" else "Record is unavailable in this server selection."
            raise ToolError(json.dumps({"error": {"code": exc.code, "message": message}}, separators=(",", ":"))) from None

    @server.tool()
    def recall(query: QueryText, limit: Annotated[int, Field(ge=1, le=100)] = 10, include_history: bool = False) -> dict[str, Any]:
        """Search only this server's authorized memory selection."""
        return invoke(lambda: retrieval.search(vault, query, limit=limit, include_history=include_history, **selection))

    @server.tool()
    def context(query: QueryText, budget_bytes: Annotated[int, Field(ge=256, le=100_000)] = 8000) -> Annotated[CallToolResult, dict[str, Any]]:
        """Build a packet whose model-facing text obeys the UTF-8 byte budget."""
        def operation():
            packet = retrieval.context(vault, query, budget_bytes=budget_bytes, **selection)
            # An explicit content block prevents the SDK's default pretty JSON
            # serialization from adding whitespace beyond the packet budget.
            return CallToolResult(
                content=[TextContent(text=retrieval.encode_packet(packet))],
                structured_content=packet,
            )
        return invoke(operation)

    @server.tool()
    def show(record_id: Identifier) -> dict[str, Any]:
        """Show a permitted record, including its historical state."""
        return invoke(lambda: clean_record(read_record(record_id)))

    @server.tool()
    def history(record_id: Identifier) -> dict[str, Any]:
        """Show permitted revisions in a record's lineage."""
        def operation():
            read_record(record_id)
            return {"records": [clean_record(record) for record in vault.history(record_id) if visible(record)]}
        return invoke(operation)

    @server.tool()
    def remember(title: ShortText, body: BodyText, kind: ShortText = "note", aliases: AliasList | None = None, sources: SourceList | None = None, evidence: Literal["user-statement", "source-excerpt", "agent-inference", "observation"] = "agent-inference", operation_id: Identifier | None = None, state: Literal["active", "proposed"] = "active") -> dict[str, Any]:
        """Write within this server's fixed project or personal scope."""
        def operation():
            validate_sources(sources)
            return clean_record(vault.put(title=title, body=body, scope=write_scope, kind=kind, aliases=aliases, sources=sources, evidence=evidence, operation_id=operation_id, actor="mcp", state=state))
        return invoke(operation, writes=True)

    @server.tool()
    def correct(record_id: Identifier, expected_revision: Identifier, title: ShortText, body: BodyText, aliases: AliasList | None = None, sources: SourceList | None = None, operation_id: Identifier | None = None) -> dict[str, Any]:
        """Correct only an owned record with the expected revision."""
        def operation():
            record = read_record(record_id)
            if record["scope"] != write_scope:
                raise VaultError("write_denied", "Record is read-only in this server selection.")
            validate_sources(sources)
            return clean_record(vault.correct(record_id, expected_revision=expected_revision, title=title, body=body, aliases=aliases, sources=sources, operation_id=operation_id, actor="mcp"))
        return invoke(operation, writes=True)

    return server
