"""Real SDK stdio subprocess checks; the optional extra enables these tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "Install the mcp extra to exercise the stdio protocol")
class McpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("remember_dammit.storage"), "MCP requires the real storage.Vault implementation")
        from remember_dammit.storage import Vault
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        self.client_type = Client
        self.parameters_type = StdioServerParameters
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Vault.initialize(Path(self.temp.name) / "vault")
        self.foreign = self.vault.put(title="Forbidden", body="Foreign project secret", scope="project:beacon")
        self.personal = self.vault.put(title="Private", body="Personal private secret", scope="personal")

    def client(self, *, personal=False):
        selection = ["--personal"] if personal else ["--project", "atlas"]
        return self.client_type(self.parameters_type(
            command=sys.executable,
            args=["-m", "remember_dammit", "--vault", str(self.vault.root), "mcp", *selection],
            env=dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1"),
        ))

    async def test_stdio_write_recall_and_bounded_schema(self):
        async with self.client() as client:
            tools = (await client.list_tools()).tools
            names = {tool.name for tool in tools}
            self.assertTrue({"remember", "recall", "context", "show", "correct", "history"} <= names)
            self.assertFalse({"grant", "revoke", "list_records"} & names)
            for tool in tools:
                self.assertFalse({"project", "personal", "scope", "vault"} & set(tool.input_schema.get("properties", {})))
            remember_schema = next(t.input_schema for t in tools if t.name == "remember")
            self.assertIn("maxLength", remember_schema["properties"]["body"])
            result = await client.call_tool("remember", {"title": "Mail", "body": "Use Postmark"})
            self.assertFalse(result.is_error)
            record = result.structured_content
            self.assertEqual(record["scope"], "project:atlas")
            result = await client.call_tool("recall", {"query": "Postmark"})
            self.assertFalse(result.is_error)
            self.assertIn("Use Postmark", json.dumps(result.structured_content))

    async def test_overview_is_fixed_scope_and_includes_exact_source_backlinks(self):
        source = self.vault.put(title="Launch goal", body="Write a guide.", kind="source", scope="project:atlas")
        task = self.vault.put(title="First task", body="Create the guide example.", kind="task",
                              scope="project:atlas", sources=[source["id"]])
        async with self.client() as client:
            result = await client.call_tool("overview", {"limit": 10})
        self.assertFalse(result.is_error)
        report = result.structured_content
        self.assertEqual(report["total_count"], 2)
        self.assertEqual(report["summary"]["by_kind"]["task"], 1)
        records = {item["id"]: item for item in report["records"]}
        self.assertEqual(records[source["id"]]["backlinks"][0]["id"], task["id"])
        for hidden in (self.foreign, self.personal):
            self.assertNotIn(hidden["id"], json.dumps(report))

    async def test_context_model_facing_text_obeys_requested_byte_budget(self):
        self.vault.put(title="Mail", body="Istanbul " * 20, scope="project:atlas")
        async with self.client() as client:
            result = await client.call_tool("context", {"query": "Mail", "budget_bytes": 1100})
        self.assertFalse(result.is_error)
        text_blocks = [block.text for block in result.content if block.type == "text"]
        self.assertEqual(len(text_blocks), 1)
        text = text_blocks[0]
        self.assertLessEqual(len(text.encode("utf-8")), 1100)
        self.assertTrue(text.endswith("}"))
        self.assertEqual(json.loads(text), result.structured_content)
        self.assertEqual(result.structured_content["records"][0]["body"], ("Istanbul " * 20).strip())

    async def test_foreign_show_history_correction_and_sources_are_denied(self):
        async with self.client() as client:
            for name, arguments in [
                ("show", {"record_id": self.foreign["id"]}),
                ("history", {"record_id": self.foreign["id"]}),
                ("show", {"record_id": self.personal["id"]}),
                ("correct", {"record_id": self.foreign["id"], "expected_revision": self.foreign["revision"], "title": "Steal", "body": "New"}),
                ("remember", {"title": "Leak", "body": "New", "sources": [self.foreign["id"]]}),
            ]:
                result = await client.call_tool(name, arguments)
                self.assertTrue(result.is_error, name)
                self.assertNotIn("secret", json.dumps(result.model_dump()).lower())
            self.assertEqual(len(self.vault.list_records()), 2)

    async def test_granted_personal_read_does_not_allow_write_or_successor_history(self):
        self.vault.grant("atlas", self.personal["id"])
        successor = self.vault.correct(self.personal["id"], expected_revision=self.personal["revision"], title="Changed", body="Ungranted successor secret")
        async with self.client() as client:
            shown = await client.call_tool("show", {"record_id": self.personal["id"]})
            self.assertFalse(shown.is_error)
            history = await client.call_tool("history", {"record_id": self.personal["id"]})
            self.assertFalse(history.is_error)
            self.assertNotIn(successor["body"], json.dumps(history.model_dump()))
            result = await client.call_tool("correct", {"record_id": self.personal["id"], "expected_revision": self.personal["revision"], "title": "Write", "body": "Unauthorized"})
            self.assertTrue(result.is_error)

    async def test_personal_server_cannot_see_projects_and_corrects_own_record(self):
        async with self.client(personal=True) as client:
            result = await client.call_tool("show", {"record_id": self.foreign["id"]})
            self.assertTrue(result.is_error)
            result = await client.call_tool("correct", {"record_id": self.personal["id"], "expected_revision": self.personal["revision"], "title": "New", "body": "Owner correction"})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["body"], "Owner correction")

    async def test_scope_override_cannot_widen_writes_and_limits_reject_oversized_input(self):
        async with self.client() as client:
            result = await client.call_tool("remember", {"title": "Bound", "body": "Fixed scope", "scope": "project:beacon", "project": "beacon", "personal": True})
            if not result.is_error:
                self.assertEqual(result.structured_content["scope"], "project:atlas")
            self.assertFalse(any(record["title"] == "Bound" and record["scope"] != "project:atlas" for record in self.vault.list_records()))
            before = len(self.vault.list_records())
            result = await client.call_tool("remember", {"title": "Oversized", "body": "x" * 100_001})
            self.assertTrue(result.is_error)
            self.assertEqual(len(self.vault.list_records()), before)

    async def test_revocation_takes_effect_in_running_stdio_server(self):
        self.vault.grant("atlas", self.personal["id"])
        async with self.client() as client:
            result = await client.call_tool("show", {"record_id": self.personal["id"]})
            self.assertFalse(result.is_error)
            self.vault.revoke("atlas", self.personal["id"])
            result = await client.call_tool("show", {"record_id": self.personal["id"]})
            self.assertTrue(result.is_error)
            result = await client.call_tool("recall", {"query": "Personal private"})
            self.assertNotIn(self.personal["body"], json.dumps(result.model_dump()))

    async def test_revoked_source_hides_dependent_show_and_history(self):
        self.vault.grant("atlas", self.personal["id"])
        dependent = self.vault.put(title="Derived", body="Derived from personal source", scope="project:atlas", sources=[self.personal["id"]])
        async with self.client() as client:
            shown = await client.call_tool("show", {"record_id": dependent["id"]})
            self.assertFalse(shown.is_error)
            self.vault.revoke("atlas", self.personal["id"])
            for tool in ("show", "history"):
                result = await client.call_tool(tool, {"record_id": dependent["id"]})
                self.assertTrue(result.is_error)
                self.assertNotIn(dependent["body"], json.dumps(result.model_dump()))

    async def test_revoked_transitive_source_hides_dependent_record(self):
        self.vault.grant("atlas", self.personal["id"])
        first = self.vault.put(title="First derivation", body="First derived text", scope="project:atlas", sources=[self.personal["id"]])
        second = self.vault.put(title="Second derivation", body="Second derived text", scope="project:atlas", sources=[first["id"]])
        self.vault.revoke("atlas", self.personal["id"])
        async with self.client() as client:
            result = await client.call_tool("show", {"record_id": second["id"]})
        self.assertTrue(result.is_error)
        self.assertNotIn(second["body"], json.dumps(result.model_dump()))


if __name__ == "__main__":
    unittest.main()
